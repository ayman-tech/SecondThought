import { wordChanges } from "./lifecycle.js";

const draft = document.getElementById("example-draft");
const suggestion = document.getElementById("example-suggestion");
const rewrite = document.getElementById("example-rewrite");
const action = document.getElementById("extension-demo-action");
const status = document.getElementById("extension-demo-status");
const originalText = draft.textContent;
const rewrittenText = rewrite.textContent;

rewrite.replaceChildren(
  ...wordChanges(originalText, rewrittenText).map(({ text, added }) => {
    if (!added) return document.createTextNode(text);
    const highlight = document.createElement("mark");
    highlight.textContent = text;
    return highlight;
  }),
);
suggestion.hidden = true;
document.getElementById("extension-demo-actions").hidden = false;

let step = "review";
action.addEventListener("click", () => {
  if (step === "review") {
    suggestion.hidden = false;
    action.textContent = "Replace";
    status.textContent = "Review the highlighted changes.";
    step = "replace";
  } else if (step === "replace") {
    draft.textContent = rewrittenText;
    suggestion.hidden = true;
    action.textContent = "Undo";
    status.textContent = "Only the flagged text changed.";
    step = "undo";
  } else {
    draft.textContent = originalText;
    action.textContent = "SecondThought?";
    status.textContent = "Original wording restored.";
    step = "review";
  }
});

const profiles = document.querySelector(".landing-profiles");
const profileName = document.getElementById("profile-name");
const profileResponse = document.getElementById("profile-response");
const profileDraft = document.getElementById("profile-draft").textContent;
const featureCheckboxes = [...profiles.querySelectorAll("input[type=checkbox]")];

// Compose a fixed example from editable parts so every combination keeps the task and deadline.
const wording = {
  casual: {
    rough: "So the summary, it needs work.",
    fluent: "The summary needs some work.",
    direct: "Fix it and send it back by Friday.",
    polite: "Could you please fix it and send it back by Friday?",
  },
  formal: {
    rough: "Regarding the summary, it requires revision.",
    fluent: "The summary requires revision.",
    direct: "Revise it and return it by Friday.",
    polite: "Could you please revise it and return it by Friday?",
  },
};

function updateProfile() {
  const selected = featureCheckboxes.filter((checkbox) => checkbox.checked);
  const features = new Set(selected.map((checkbox) => checkbox.value));
  profileName.textContent = selected.length
    ? selected.map((checkbox) => checkbox.labels[0].textContent.trim()).join(" + ")
    : "Original draft";

  const style = features.has("formality") ? wording.formal : wording.casual;
  const assessment = features.has("fluency") ? style.fluent : style.rough;
  const request = features.has("politeness") ? style.polite : style.direct;
  const acknowledgment = features.has("empathy") ? "I know this is a tight turnaround. " : "";
  profileResponse.textContent = selected.length
    ? `${acknowledgment}${assessment} ${request}`
    : profileDraft;
}

profiles.addEventListener("change", updateProfile);
updateProfile();
profiles.hidden = false;
