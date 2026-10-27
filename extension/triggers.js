// Rule-based check for wording that deserves a second thought. It runs inside
// the page on every pause in typing, so it has to be instant and private: no
// model, no network, just word lists and a few patterns.
const SecondThoughtTriggers = (() => {
  const SWEARING = new Set([
    "damn", "dammit", "crap", "crappy", "shit", "shitty", "bullshit", "shitshow",
    "fuck", "fucking", "fucked", "wtf", "ass", "asshole", "bloody", "bitch", "pissed",
  ]);
  const INSULTS = new Set([
    "idiot", "idiots", "idiotic", "stupid", "dumb", "moron", "moronic", "useless",
    "pathetic", "ridiculous", "garbage", "trash", "lazy", "incompetent", "jerk",
    "clueless", "brainless", "sloppy", "screwup", "nonsense", "whining", "loser",
    "clown", "smug",
  ]);
  // Only matched in lowercase, so "R" (the language) or "U.S." don't count.
  const TEXTING = new Set([
    "u", "ur", "r", "pls", "plz", "gonna", "wanna", "gotta", "tbh", "idk", "lol",
    "omg", "b4", "thx", "cuz", "coz", "ya", "yall",
  ]);
  const PHRASES = [
    /\b(?:what|who|where|why|how) the hell\b/i,
    /\bas hell\b/i,
    /\bshut up\b/i,
    /\bscrew(?:ed|ing)? (?:up|around)\b/i,
    /\bout of your ass\b/i,
    /\bdid you even\b/i,
    /\bstop ignoring\b/i,
    /\b(?:is|was|are) a (?:joke|disaster|mess)\b/i,
    /\bknow-it-all\b/i,
  ];
  // Common all-caps words that aren't shouting.
  const ACRONYMS = new Set(["ASAP", "FYI", "TODO", "NOTE", "EOD", "JSON", "HTML", "HTTP", "HTTPS", "UTC", "CEST", "PST", "EST"]);

  function check(text) {
    const reasons = [];
    const add = (label, word) => {
      if (!reasons.some((r) => r.word === word)) reasons.push({ label, word });
    };

    for (const word of text.match(/[A-Za-z0-9']+/g) || []) {
      const lower = word.toLowerCase();
      if (SWEARING.has(lower)) add("swearing", word);
      else if (INSULTS.has(lower)) add("harsh", word);
      else if (word === lower && TEXTING.has(word)) add("casual", word);
    }
    for (const pattern of PHRASES) {
      const match = text.match(pattern);
      if (match) add("harsh", match[0]);
    }
    const shouted = (text.match(/\b[A-Z]{4,}\b/g) || []).filter((w) => !ACRONYMS.has(w));
    if (shouted.length >= 2) add("shouting", shouted.slice(0, 2).join(" "));
    const punctuation = text.match(/[!?]{2,}/);
    if (punctuation) add("shouting", punctuation[0]);

    return reasons;
  }

  return { check };
})();
