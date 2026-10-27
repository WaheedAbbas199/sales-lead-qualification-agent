# Roman Urdu + English notes (revision)

* **Deterministic scoring**: score Python rules se nikalta hai, LLM se nahi. Isliye same lead = same score, aur injection se score nahi badal sakta.
* **Unknown vs not_matched**: `unknown` ka matlab data hi nahi (0 points, lekin "no" nahi). `not_matched` ka matlab data hai magar fit nahi.
* **Human-in-the-loop**: workflow `human_review` par ruk jata hai. Reviewer approve kare tab hi status badalta aur draft banta hai. Decision DB se dobara parha jata hai (fail closed).
* **Prompt injection**: lead ka text sirf *data* hai. Hum usay random delimiter me daalte hain, model ko tools nahi dete, output schema se validate karte hain.
* **Immutable evaluations**: recalculation purani history delete nahi karti, nayi row banati hai (ICP version ke saath) — isse result reproducible rehta hai.
* **Partial unique index**: DB khud guarantee deta hai ke ek lead ka sirf ek active workflow ho (race condition safe).
* **Provenance**: har fact ka source dikhta hai: user_provided, verified_source, search_snippet (proof nahi), ai_inferred.
* **Confidence**: evidence kitna kaafi hai — deal jeetne ki probability nahi.
