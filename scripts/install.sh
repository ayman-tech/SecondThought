#!/bin/sh
# SecondThought installer for macOS and Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/ayman-tech/SecondThought/master/scripts/install.sh | sh
#
# Sets everything up in your home folder (no sudo needed) and finishes with
# three clicks in your browser. Run it again any time to update.
#
# Optional, set before running:
#   SECONDTHOUGHT_HOME   where to install (default: ~/SecondThought)
#   SECONDTHOUGHT_MODEL  path to the both-t5 model folder or its .zip
set -eu

REPO="https://github.com/ayman-tech/SecondThought"
DIR="${SECONDTHOUGHT_HOME:-$HOME/SecondThought}"
MODEL_DIR="$DIR/models/both-t5"
EXTENSION_DIR="$DIR/extension/frontend"

step() { printf '\n\033[35m==> %s\033[0m\n' "$1"; }
note() { printf '    %s\n' "$1"; }
warn() { printf '    \033[33m! %s\033[0m\n' "$1"; }

printf '\033[35mSecondThought installer\033[0m\n'
note "Installing to $DIR"

# 1. uv installs Python and the project's packages, without sudo.
step "Checking for uv"
if ! command -v uv >/dev/null 2>&1; then
    note "Installing uv (https://docs.astral.sh/uv/)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
fi
note "$(uv --version)"

free_kb=$(df -Pk "$HOME" | awk 'NR == 2 { print $4 }')
if [ "${free_kb:-0}" -lt 4194304 ]; then
    warn "Only $((free_kb / 1048576)) GB free. SecondThought needs about 4 GB."
fi

# 2. The project: git if it's there, a download if not.
step "Getting SecondThought"
if command -v git >/dev/null 2>&1; then
    if [ -d "$DIR/.git" ]; then
        git -C "$DIR" pull --ff-only --quiet
        note "Updated to the latest version."
    else
        git clone --depth 1 --quiet "$REPO" "$DIR"
        note "Downloaded."
    fi
else
    mkdir -p "$DIR"
    # Unpacks over the old files but keeps the model and environment already there.
    curl -fsSL "$REPO/archive/refs/heads/master.tar.gz" | tar -xz -C "$DIR" --strip-components=1
    note "Downloaded (no git found, so used the archive)."
fi

# 3. Python and packages.
step "Installing what it needs (a few minutes the first time)"
unset VIRTUAL_ENV  # always use SecondThought's own environment
(cd "$DIR" && uv sync --extra evaluation)
note "Done."

# 4. The rewriting model isn't public yet, so it comes from the team.
step "Checking for the rewriting model"
if [ -f "$MODEL_DIR/model.safetensors" ]; then
    note "Found models/both-t5."
elif [ -n "${SECONDTHOUGHT_MODEL:-}" ] && [ -e "$SECONDTHOUGHT_MODEL" ]; then
    mkdir -p "$DIR/models"
    case "$SECONDTHOUGHT_MODEL" in
        *.zip) (cd "$DIR" && uv run python -m zipfile -e "$SECONDTHOUGHT_MODEL" models) ;;
        *) cp -R "$SECONDTHOUGHT_MODEL" "$MODEL_DIR" ;;
    esac
    if [ -f "$MODEL_DIR/model.safetensors" ]; then
        note "Copied the model into models/both-t5."
    else
        warn "Couldn't find model.safetensors in $SECONDTHOUGHT_MODEL. Copy the both-t5 folder to $MODEL_DIR yourself."
    fi
else
    warn "One manual step: copy the both-t5 model folder (ask the team) to"
    warn "  $MODEL_DIR"
fi

# 5. A way to start the service. On macOS the .command file is double-clickable.
step "Creating the start script"
START="$DIR/start-secondthought.sh"
cat > "$START" <<'EOF'
#!/bin/sh
cd "$(dirname "$0")"
unset VIRTUAL_ENV
echo "Starting SecondThought. Keep this window open while you use it."
exec uv run python -m extension.api.server
EOF
chmod +x "$START"
if [ "$(uname)" = "Darwin" ]; then
    cp "$START" "$DIR/start-secondthought.command"
    chmod +x "$DIR/start-secondthought.command"
    note "Double-click start-secondthought.command in $DIR to start it."
else
    note "Run $START to start it."
fi

if curl -fs --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    warn "Something is already running on port 8000. Close it (maybe an older SecondThought) before starting."
fi

# 6. Open the browser's extensions page and the folder to load.
step "Adding it to your browser"
name="your browser"
page="chrome://extensions"
if [ -z "${SECONDTHOUGHT_NO_BROWSER:-}" ]; then
    if [ "$(uname)" = "Darwin" ]; then
        for app in "Google Chrome:chrome" "Microsoft Edge:edge" "Brave Browser:brave"; do
            if [ -d "/Applications/${app%%:*}.app" ]; then
                name="${app%%:*}"
                page="${app##*:}://extensions"
                open -a "$name" "$page" || true
                break
            fi
        done
        open "$EXTENSION_DIR" || true
    else
        for cmd in google-chrome:chrome chromium:chrome chromium-browser:chrome microsoft-edge:edge brave-browser:brave; do
            if command -v "${cmd%%:*}" >/dev/null 2>&1; then
                name="${cmd%%:*}"
                page="${cmd##*:}://extensions"
                ("${cmd%%:*}" "$page" >/dev/null 2>&1 &) || true
                break
            fi
        done
        if command -v xdg-open >/dev/null 2>&1; then xdg-open "$EXTENSION_DIR" >/dev/null 2>&1 || true; fi
    fi
fi

printf '\n\033[32mAlmost there. In %s (%s):\033[0m\n' "$name" "$page"
note "1. Switch on Developer mode (top right)."
note "2. Click Load unpacked and choose this folder:"
note "   $EXTENSION_DIR"
note "3. Start SecondThought (see above), then type something heated in Gmail or Slack."
printf '\n'
