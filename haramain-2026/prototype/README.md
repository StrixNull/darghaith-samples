# هَوْنًا إلى الروضة — Hawnan: Gently to the Rawdah

> نموذج أولي عامل لمشاركة الفريق في **فكّر للحرمين 2026** (التحدي: تجربة الوصول والانتظار والدخول للروضة الشريفة).
> المفهوم الكامل في `../docs/03-concept.md`. القاعدة: **لا نبالغ في وصف ما بُني، ونسمّي كل بيانات محاكاة بأنها محاكاة، والعرض لا يعتمد على الشبكة أبداً.**

## التشغيل · Run

```bash
cd haramain-2026/prototype
pip install -r requirements.txt
uvicorn app.main:app --port 8010
# then open http://localhost:8010/
```

- الخدمة تعمل دون إنترنت: لا CDN، لا نموذج لغوي، لا اتصال خارجي. خطوط Google اختيارية وتُحمَّل فقط إذا كان الجهاز متصلاً، والبديل خط النظام.
- قاعدة البيانات `hawnan.sqlite3` تُنشأ وتُملأ تلقائياً عند أول تشغيل بتغذية تصاريح **محاكاة معلنة** (4 نقاط انتظار، 1152 تصريحاً، أزمنة مراحل موسومة `source="simulated"`). لإعادة يوم العرض من البداية: احذفوا الملف أو استدعوا `POST /api/supervisor/reset` برمز الجهاز.
- رمز جهاز المشرف في العرض: `demo-staff-1` (يُضبط بالمتغير `HAWNAN_STAFF_TOKENS`). المفاتيح كلها لها قيم عرض افتراضية وتُضبط بالمتغيرات `HAWNAN_SEAL_SECRET`، `HAWNAN_CONTENT_KEY`، `HAWNAN_AUDIT_KEY`، `HAWNAN_PERMIT_SALT`.
- للعرض على نقطة اتصال (hotspot): شغّلوا الخادم بـ `--host 0.0.0.0` وافتحوا `http://<عنوان اللابتوب>:8010/guest` على الهواتف. تثبيت الـ PWA يتطلب HTTPS أو localhost؛ الصفحة تعمل كاملة دونه (تُحفظ آخر حالة محلياً).

## عرض ثلاث دقائق · Demo steps

1. **الضيفة «سيتي»** — افتحوا `/guest?lang=id&permit=NSK-SITI-0820`: رسالة T-24h بالإندونيسية بالبوابة ونقطة التجمع ووقت الانطلاق المحسوب لسرعة مشي كبار السن.
2. **محطة التحقق** — `/checkin`: اقرؤوا `NSK-SITI-0820` مرة واحدة → تصريح فوج موقّع (QR + نسخة ورقية للطباعة). الصقوا نص التصريح في «تحقق» لتروا التحقق دون اتصال بنسك. غيّروا حرفاً لتروا الرفض.
3. **بطاقة الانتظار** — من زر «فتح بطاقة الضيف»: الفوج 14، «نحو 12–18 دقيقة» (مدى، لا عدّ تنازلي)، التعليمة الحالية بالإندونيسية مع رمز تصويري، وبطاقات «أرني» تنقلب إلى العربية بخط كبير. افتحوا الصفحة نفسها بالأردية على هاتف ثانٍ (`/guest?lang=ur&pass=…`).
4. **النداء الصامت** — `/staff?point=W1`: اضغطوا «تقدموا بهدوء» → تتغير `/display?point=W1` والهواتف في اللحظة نفسها بصمت. قدّموا الفوج 13 ثم 14: عند «تهيئة» تظهر بطاقة التهيئة، وعند «داخل» تُعتم الشاشة: لا شيء على الشاشة داخل الروضة.
5. **غرفة القرار** — `/ops`: الإشغال والتدفق وتنبيه التباطؤ من أحداث الأفواج فقط، حالة مراجعة حزم المحتوى، ثم شغّلوا التوأم الرقمي: 3 تحققات مقابل تحقق واحد، ونوافذ وصول متدرجة. الرقم يخرج من المحرك نفسه الذي شغّل الهاتف قبل دقيقة.

## What is real, what is simulated

| Layer | Status |
|---|---|
| Batch clock (event-sourced), estimator (p20–p80 ranges), Silent Seal (signed pass, Base45 QR, offline constant-time verify), Silent Call (20 instructions × 10 languages, one active per point), signed content packs, journey messages, indicators, digital twin, HMAC-chained audit log | **Real** — working, typed, unit-tested (`pytest`: 63 tests) |
| Permit times and guest languages (the Nusuk feed) | **Simulated and declared** — `app/seed.py` is the `SimulatedPermitFeed`; every page shows «بيانات تصاريح محاكاة معلنة»; `/api/runtime` reports `simulated_permit_feed: true` |
| Stage durations and release intervals | **Simulated** until the Phase-0 stopwatch measurements in Madinah; the estimator reports its basis (`measured` / `simulated` / `prior`) and the UI prints it under the range |
| Etiquette and preparation text | Generic lines in the spirit of the Authority's published guidance, wording pending Authority and scholarly review; Arabic and English reviewed by the team, the other eight languages are drafts flagged `"reviewed": false` (listed on the ops page, never shown to guests) |
| Gate names, hotel areas, the "protected slot" promise | Placeholders and a policy for the Authority to confirm; the default message promises only re-batching |
| Signature scheme | Ed25519 via `cryptography` when importable, else HMAC-SHA256 — `/api/runtime` → `seal.scheme` says which is active |
| Content-pack signatures | HMAC-SHA256 with a team key (`python -m hawnan_core.content sign content/`); the Authority's key in production |

No names, passports or phone numbers exist anywhere in the system. The permit reference is stored only as a salted hash; the pass carries `{v, batch, point, lane, protected_until, issued_at}` and nothing else. No AI is used at runtime.

## Page map

| Path | Role |
|---|---|
| `/` | Landing: what this is, the roles, the demo steps, real vs simulated |
| `/guest` | Guest phone (PWA-style): language picker (native names), journey message, batch pass QR, holding card with range + instruction + Show-Me cards, preparation card, dark "inside" state. Polls every 3 s, keeps the last state offline. Params: `lang`, `pass`, `permit` |
| `/checkin` | Check-in station: read a (simulated) permit once → signed batch pass, paper copy, offline verify panel |
| `/staff?point=W1` | Supervisor tablet: queue, advance batches, 20 instructions with pictograms in Arabic + the languages present at the point, audit log. Header `X-Device-Token` |
| `/display?point=W1` | Holding-point screen: current and next batch, active instruction in Arabic + the three most common languages |
| `/ops` | Decision room: occupancy, throughput, slowdown alerts, batch timeline, content review status, digital twin |

## API

`GET /api/runtime` · `GET /api/points` · `GET /api/permits/sample` · `POST /api/checkin {permit_ref, lang?}` · `POST /api/verify {pass}` · `GET /api/point/{id}/state?lang=` · `GET /api/point/{id}/batches` · `GET /api/batch/{id}?lang=` · `POST /api/supervisor/instruction {point_id, instruction_id|null}` · `POST /api/supervisor/advance {batch_id}` · `POST /api/supervisor/reset` · `GET /api/journey/{permit_ref}?lang=` · `GET /api/showme?lang=&batch_id=` · `GET /api/content/{languages|ui|preparation|instructions|journey|showme|review}?lang=` · `GET /api/indicators` · `POST /api/twin/run {…params, compare}` · `GET /api/audit/verify` · `GET /api/audit/recent`

Supervisor endpoints need the `X-Device-Token` header. POST endpoints are rate-limited per device. Every response carries security headers and a same-origin CSP; a per-device HttpOnly cookie identifies the device anonymously in the audit log.

## Layout

```
prototype/
├── hawnan_core/      pure Python engine, no I/O: batch_clock, estimator, seal, silent_call, content, journey, indicators, twin, audit
├── app/              FastAPI service (main.py), SQLite store (store.py), declared simulated feed (seed.py)
├── content/          signed content packs, one JSON per language (ar en ur id tr bn fr ms ha fa)
├── web/              the six pages + static/ (hawnan.css, hawnan.js, qr.js, sw.js, manifest, icon)
├── tests/            pytest (core + API with httpx TestClient)
└── docs/screenshots/ guest-id, staff, display, ops, checkin
```

## Tests

```bash
python3 -m pytest -q          # 63 tests: transitions, ranges, seal sign/verify/tamper/expiry, single-active rule,
                              # unsigned-pack refusal, journey rendering ×10 languages, indicators, twin determinism
                              # (1 check < 3 checks on the pressure proxy), audit chain, API flow checkin → verify → state → instruction → advance
python3 -m hawnan_core.content verify content/   # pack signatures
```

## Team conventions kept

Western digits everywhere (no Arabic-Indic digits in packs or UI), RTL for ar/ur/fa and LTR otherwise, native-script language names without flags, no sounds, no gamification, no dark patterns; white background, deep teal, mint tints, gold used sparingly, slate text — the palette of the official briefs.
