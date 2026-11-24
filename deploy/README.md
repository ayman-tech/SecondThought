# AWS demo deployment — us-east-2

Target: a paid AWS account with approximately $120 remaining promotional credit,
one `g4dn.xlarge`, and initial access through an SSH tunnel. No domain, load
balancer, NAT gateway, database, teacher API key, or public application port is
required. The website and its single Qwen worker run in one container.

The default deployment serves the versioned seven-feature catalog. Synthetic
empathy experiment files under `data/synthetic/` are deliberately excluded.
Deploying a successor catalog is a separate explicit release decision.

## 1. Check credits, quota, and spending before launch

In **Billing and Cost Management → Credits**, select the active credit and check:
amount remaining, expiry, and the exact applicable services. Confirm Amazon EC2
and the storage/network charges you expect are covered. A paid account can incur
charges after eligible credits expire or run out; a visible balance alone does
not establish that every resource is covered.

Create a monthly **cost budget** (for example $25) with email notifications at
50%, 80%, and 100%. Track gross usage excluding credits when configuring cost
filters so consuming credits does not hide resource spending. Review the Bills
page as well. Budget alerts can be delayed and do not themselves stop resources.

Set the AWS console region to **US East (Ohio), us-east-2**. Under **Service
Quotas → AWS services → Amazon EC2**, find **Running On-Demand G and VT
instances**. Request **4 vCPUs** if the current quota is less than 4. GPU quota
approval and actual capacity are separate from credit eligibility. Do not launch
a larger GPU to work around a quota/capacity error without checking its price.

References: [credits](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-credits.html),
[plans](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html),
[GPU quotas](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html),
[budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html).

## 2. Understand the demo budget

Use the actual Linux On-Demand quote shown in the EC2 launch console for
`g4dn.xlarge` in **us-east-2**. The table below is a planning example using
**$0.60/hour compute**, **80 GiB gp3 at $0.08/GiB-month**, and **one public IPv4 at
$0.005/hour**. These are explicit budgeting assumptions, not a guaranteed quote
or a statement of your credit eligibility. Check them in the
[AWS calculator](https://calculator.aws/), [EC2 pricing](https://aws.amazon.com/ec2/pricing/on-demand/),
[EBS pricing](https://aws.amazon.com/ebs/pricing/), and
[IPv4 pricing](https://aws.amazon.com/vpc/pricing/).

| Runtime in one month | Compute | 80 GiB disk retained one month | IPv4 while running | Example total |
|---|---:|---:|---:|---:|
| 20 hours | $12.00 | $6.40 | $0.10 | $18.50 |
| 50 hours | $30.00 | $6.40 | $0.25 | $36.65 |
| 100 hours | $60.00 | $6.40 | $0.50 | $66.90 |
| 150 hours | $90.00 | $6.40 | $0.75 | $97.15 |
| 720 hours | $432.00 | $6.40 | $3.60 | $442.00 |

Totals exclude transfer, snapshots, taxes, paid AMI software, other AWS workloads,
and optional services. Credits apply only to eligible costs. Default gp3 IOPS and
throughput are sufficient for this pilot; additional provisioned performance can
add costs. Prefer short On-Demand sessions initially; Spot may interrupt demos.

**Stop the EC2 instance after a session.** Stopping the container or closing the
browser does not stop EC2 compute billing. Disk persists and is billed while the
instance is stopped. Avoid an Elastic IP for this tunnel-based pilot: the
auto-assigned public IP can change after stop/start, but you do not need to pay
to reserve an address. Delete unused snapshots and volumes when finished.
See [billing by instance state](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html).

## 3. Launch exactly one instance in the console

1. EC2 → **Launch instance**, name `secondthought-demo`.
2. Select an **AWS-published Deep Learning Base OSS NVIDIA Driver GPU AMI,
   Ubuntu 24.04, x86_64**. Confirm the publisher and software pricing. Use the
   current regional AMI rather than copying an AMI ID from another region.
   We use our own pinned PyTorch container, so a large preinstalled framework
   image is unnecessary. [AWS DLAMI releases](https://docs.aws.amazon.com/dlami/latest/devguide/what-is-dlami.html).
3. Instance type: **g4dn.xlarge**, On-Demand. Confirm the displayed price before
   pressing Launch. It has one T4 GPU, 4 vCPUs, and 16 GiB host memory.
4. Create an SSH key pair, save the private key locally outside this repository.
5. Use a public subnet with an internet-gateway route and **Auto-assign public
   IP enabled**. No NAT gateway is required for this single public host.
6. Security group: inbound **TCP 22 from My IP only**. Leave 80, 443 and 8001
   closed for this first private test. Allow outbound HTTPS for image/model downloads.
7. Root storage: **80 GiB gp3**, default performance. Confirm any extra disks in
   the AMI and remove ones not needed. Avoid adding paid Marketplace software.
8. Advanced details: **shutdown behavior = Stop**; metadata **IMDSv2 required**.
9. Launch one instance and record its **instance ID and public IPv4 address**.

## 4. Connect and check Docker/GPU access

On your Mac, substituting your saved key path and the instance's public IP:

```sh
chmod 400 ~/Downloads/secondthought-demo.pem
ssh -i ~/Downloads/secondthought-demo.pem ubuntu@PUBLIC_IP
```

On EC2:

```sh
nvidia-smi
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

The GPU-ready AMI should include the driver and container toolkit. If `docker
compose` or `nvidia-ctk` is absent, install them using the official
[Docker Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/) and
[NVIDIA toolkit instructions](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
CUDA 12.8 containers require a compatible NVIDIA host driver; use a current DLAMI.

Set a two-hour automatic shutdown timer for the session:

```sh
sudo shutdown -P +120
```

With EC2 shutdown behavior set to Stop, this powers down the instance. Cancel
the timer with `sudo shutdown -c` when necessary; remember to stop it manually
afterward. Schedule a new timer at each session; it is not a persistent billing cap.

## 5. Transfer the code

You can clone a pushed branch that contains these deployment files. Until then,
the allowlisted source packager transfers the working deployment without
including `.env`, API keys, SSH keys, model caches, datasets or research notebooks.

On your Mac, from the repository root:

```sh
.venv/bin/python deploy/package_source.py
scp -i ~/Downloads/secondthought-demo.pem /tmp/secondthought-demo-source.tar.gz ubuntu@PUBLIC_IP:~/
```

On EC2:

```sh
tar -xzf ~/secondthought-demo-source.tar.gz -C ~
cd ~/SecondThought
```

For later updates, stop the app and extract a fresh package into a fresh directory
or use Git. Avoid overlaying releases with removed files. Docker's named model
cache volume survives source-directory changes because the Compose project name
is fixed.

## 6. Build, cache the model, and start the lab

On EC2, from `~/SecondThought`, use both Compose files for GPU:

```bash
DC=(sudo docker compose -f deploy/compose.yaml -f deploy/compose.gpu.yaml)
"${DC[@]}" build app
"${DC[@]}" run --rm app python -c 'import torch; print(torch.__version__, torch.cuda.is_available()); assert torch.cuda.is_available()'
"${DC[@]}" run --rm app python deploy/cache_model.py
"${DC[@]}" up -d
"${DC[@]}" logs -f --tail=100 app
```

Use Ctrl-C to exit logs; the service keeps running. The first build/download can
take several minutes. The named volume persists the pinned Hugging Face model
between container and instance restarts. No Hugging Face token or OpenAI API key
is required for this public model.

The lockfile installs CPU PyTorch on Linux. The GPU image explicitly replaces it
with **PyTorch 2.8.0 CUDA 12.8**, using the
[official PyTorch wheel backend](https://pytorch.org/get-started/previous-versions/).
Startup validates GPU availability and all catalog artifacts instead of silently
falling back to CPU. **Do not use `uv run` inside the built GPU container**; it
can resynchronize the CPU lockfile. Its command uses the venv Python directly.

Deployment defaults to **float32**, preserving the Mac experiment precision
choice. GPU and MPS can still produce different outputs; check parity rather
than assuming identical text. There is exactly **one Uvicorn worker** because
the model, cancellation and latest-request queue are process-local. Do not use
`--reload` or increase workers for this deployment.

Check readiness on EC2:

```sh
curl --fail http://127.0.0.1:8001/health/ready
sudo docker compose -f deploy/compose.yaml -f deploy/compose.gpu.yaml ps
```

The page can render before the model is ready. `/health/ready` must return HTTP
200 before testing generation. The container health check allows 15 minutes for
initial startup; it is not a promise that startup takes that long.

## 7. Open the website through the SSH tunnel

In a new terminal on your Mac:

```sh
ssh -i ~/Downloads/secondthought-demo.pem -N -L 8004:127.0.0.1:8001 ubuntu@PUBLIC_IP
```

Open **http://127.0.0.1:8004/explore**. Keep this tunnel running. This is private
access for your machine; other testers need their own authorized tunnel. For a
public demo URL later, add a domain, HTTPS proxy, access control, and streaming
configuration. The current files deliberately bind the host port to loopback.

Smoke-test a short input, alpha 0, then one feature/layer at +0.5. Check mean and
last-token pooling, cancellation after slider movement, two-feature composition,
and the applied vector IDs under run details. Use short output budgets initially.
Held-out layer colours are not output-quality scores.

## 8. Stop, restart, and clean up

To end a session, use **EC2 → instance → Instance state → Stop instance**.
Alternatively, use its configured OS shutdown timer. Verify EC2 shows **Stopped**.
Keep the instance ID; its public IP can change next start. The Docker service
and app restart automatically, using the retained cache. Reopen the tunnel with
the new IP and wait for readiness.

To remove containers while retaining cached weights:

```sh
sudo docker compose -f deploy/compose.yaml -f deploy/compose.gpu.yaml down
```

This does not stop the EC2 host or compute charges. `down -v` also deletes the
model cache; use it only when intentionally discarding the cache.

For permanent cleanup, terminate the instance and verify its root volume was
deleted. Remove remaining volumes, snapshots and reserved public IPs. Review
Billing for this and any unrelated AWS projects. No cloud resources are created
by committing these files or building the image locally.

## CPU fallback

If GPU quota is pending, an x86_64 Ubuntu CPU instance with at least 8 GiB RAM
can test the integration using only `deploy/compose.yaml`:

```sh
sudo docker compose -f deploy/compose.yaml build
sudo docker compose -f deploy/compose.yaml run --rm app python deploy/cache_model.py
sudo docker compose -f deploy/compose.yaml up -d
```

The same tunnel works. CPU slider responsiveness is unbenchmarked and can be
slow. Check its separate instance quote; do not assume a free-tier instance has
enough memory for this application. The GPU override is intended for NVIDIA
Linux hosts, not Docker Desktop on the Mac.
