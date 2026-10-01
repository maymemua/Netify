# PO Interview Juggler

Practice app for PO interview questions (Lending: cash loan / BNPL). Open `index.html` in a browser; there is nothing to install or build.

- **Luyện tập** – shows one random question at a time (a full shuffled pass before repeats). Type your answer (autosaved), optionally reveal the hint and draft answer, mark it *Đã ổn* / *Cần luyện thêm*, then go to the next card. Filter by group or status. Keys: ← / → when not typing.
- **Quản lý câu hỏi** – search, add, edit and delete questions; export/import everything as JSON; restore the 77 seeded questions.

Data lives in the browser's `localStorage`, so use *Xuất JSON* to back it up or move to another device.
The seed questions come from the Notion page "Bộ câu hỏi phỏng vấn PO Lending (Cash loan / BNPL)" (`questions.js`).
