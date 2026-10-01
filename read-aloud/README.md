# Read Aloud

Paste text, press Play, and it is read out loud, like Edge's "Read aloud". Open `index.html` in a browser; nothing to install or build.

It uses the browser's Web Speech API (`speechSynthesis`), so the voices are whatever the browser offers. **Microsoft Edge exposes its "Natural" online voices** (e.g. *Aria*, *Jenny*, *HoaiMy*, *NamMinh*) through this same API, so use Edge for the Edge-quality sound. Chrome and Safari work too, with their own voices.

- Voice picker grouped by language (your browser language first, Natural voices first), speed / pitch / volume.
- Current sentence and word are highlighted while reading; click any word to jump there.
- Play/Pause, previous/next sentence, Stop. Keys when not typing: Space, ← / →, Esc.
- Long text is split into sentences so engines don't cut off after ~15 s.
- Hints to switch voice when the text is Vietnamese but an English voice is selected (and vice versa).
- Text and settings are remembered in `localStorage`.
