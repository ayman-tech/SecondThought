// Settings shared by the in-page nudge, the popup and the settings page, so
// they all read the same defaults from chrome.storage.
const SecondThoughtSettings = (() => {
  const DEFAULTS = {
    nudgeEnabled: true,
    disabledSites: [],
    triggerKinds: { swearing: true, harsh: true, casual: true, shouting: true },
  };

  // The kinds of wording triggers.js can spot, as shown on the settings page.
  const KINDS = [
    { key: "swearing", label: "Swearing", examples: "damn, crap, wtf" },
    { key: "harsh", label: "Harsh words", examples: "idiot, lazy, \"did you even\"" },
    { key: "casual", label: "Texting shorthand", examples: "u, gonna, tbh" },
    { key: "shouting", label: "Shouting", examples: "ALL CAPS, \"!!\"" },
  ];

  async function load() {
    const stored = await chrome.storage.local.get(DEFAULTS);
    return { ...stored, triggerKinds: { ...DEFAULTS.triggerKinds, ...stored.triggerKinds } };
  }

  const save = (changes) => chrome.storage.local.set(changes);

  async function setSiteEnabled(site, on) {
    const { disabledSites } = await load();
    const next = disabledSites.filter((other) => other !== site);
    if (!on) next.push(site);
    await save({ disabledSites: next });
  }

  return { DEFAULTS, KINDS, load, save, setSiteEnabled };
})();
