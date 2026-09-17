#!/usr/bin/env node
/*
 * build-deck.js — regenerates Hawnan_Fakkir_lilHaramain_2026.pptx (9 slides, Arabic, 16:9).
 *
 * Run:   node build-deck.js
 * Deps:  pptxgenjs (npm install inside this folder). jszip is pulled in by pptxgenjs.
 *
 * Rules baked in: Arabic in Modern Standard with Western digits, rtlMode + align right + lang ar-SA
 * on every Arabic box, Arial everywhere (safe font), gold used once per slide, the numbered
 * "journey step" pill is the only repeated motif (no bars, no stripes), speaker notes on every slide.
 * Nothing on these slides claims more than docs/03-concept.md: the prototype is a hackathon
 * prototype, the permit feed is simulated and declared, nothing is an official Authority product.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const pptxgen = require('pptxgenjs');
const JSZip = require('jszip');

// ---------------------------------------------------------------- constants
const OUT_FILE = path.join(__dirname, 'Hawnan_Fakkir_lilHaramain_2026.pptx');
const SCREENSHOT_DIR = path.join(__dirname, '..', 'prototype', 'docs', 'screenshots');
const SCREENSHOTS = {
  guestId: path.join(SCREENSHOT_DIR, 'guest-id.png'), // Indonesian guest phone (slide 6, first frame)
  guestUr: path.join(SCREENSHOT_DIR, 'guest-ur.png'), // optional: Urdu guest phone
  staff: path.join(SCREENSHOT_DIR, 'staff-tablet.png'), // optional: supervisor tablet
};

const C = {
  teal: '006868',
  mint: '78C0B0',
  mintLight: 'A0D0C8',
  mintPale: 'E9F4F1',
  gold: 'C9A24D',
  slate: '505060',
  ink: '202020',
  white: 'FFFFFF',
  grid: 'DCE8E4',
};
const FONT = 'Arial';
const TEAM_NAME = 'فريق رؤية بلس'; // change here if the team registers under a new name
const TEAM_HOME = 'جامعة الأمير مقرن، المدينة المنورة';
const TRACK_LINE = 'فكّر للحرمين 2026 · الثقافة والقيم · تجربة زيارة الروضة الشريفة';
const FOOTER = 'نموذج أولي لهاكاثون فكّر للحرمين 2026، ليس منتجاً رسمياً للهيئة';
const TAGLINE = 'موعدك محفوظ، فامشِ إليه هونًا';

const W = 10; // LAYOUT_16x9
const H = 5.625;

// ---------------------------------------------------------------- helpers
// Every helper builds a fresh options object: pptxgenjs mutates options in place.
function ar(extra) {
  return Object.assign(
    { fontFace: FONT, rtlMode: true, align: 'right', lang: 'ar-SA', isTextBox: true, margin: 0, valign: 'top' },
    extra || {}
  );
}
function ltr(extra) {
  return Object.assign(
    { fontFace: FONT, rtlMode: false, align: 'left', lang: 'en-US', isTextBox: true, margin: 0, valign: 'top' },
    extra || {}
  );
}
function text(slide, str, x, y, w, h, opts) {
  slide.addText(str, Object.assign({ x, y, w, h }, ar(opts)));
}
function textLtr(slide, str, x, y, w, h, opts) {
  slide.addText(str, Object.assign({ x, y, w, h }, ltr(opts)));
}
function runs(slide, parts, x, y, w, h, opts) {
  // parts: [{ text, options }]; each run gets fresh options merged with the box defaults
  const items = parts.map((p) => ({ text: p.text, options: Object.assign({ fontFace: FONT, lang: 'ar-SA' }, p.options || {}) }));
  slide.addText(items, Object.assign({ x, y, w, h }, ar(opts)));
}
function shadow() {
  return { type: 'outer', color: '000000', blur: 6, offset: 2, angle: 90, opacity: 0.12 };
}
function card(pres, slide, x, y, w, h, o) {
  const opts = { x, y, w, h, rectRadius: (o && o.radius) || 0.14, fill: { color: (o && o.fill) || C.mintPale } };
  if (o && o.line) opts.line = { color: o.line, width: (o.lineWidth || 1.25) };
  else opts.line = { color: (o && o.fill) || C.mintPale, width: 0 };
  if (o && o.shadow) opts.shadow = shadow();
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, opts);
}
// The motif: a rounded "journey step" pill with a number (or a short label) inside.
function pill(pres, slide, x, y, w, h, label, o) {
  const opts = {
    x, y, w, h,
    shape: pres.shapes.ROUNDED_RECTANGLE,
    rectRadius: h / 2,
    fill: { color: (o && o.fill) || C.teal },
    color: (o && o.color) || C.white,
    fontFace: FONT,
    fontSize: (o && o.fontSize) || 12,
    bold: o && o.bold === false ? false : true,
    align: 'center',
    valign: 'middle',
    isTextBox: true,
    margin: 0,
    lang: (o && o.lang) || 'ar-SA',
    rtlMode: !(o && o.lang && o.lang !== 'ar-SA'),
  };
  if (o && o.line) opts.line = { color: o.line, width: o.lineWidth || 1.25 };
  slide.addText(String(label), opts);
}
function circle(pres, slide, x, y, d, fill, lineColor) {
  const opts = { x, y, w: d, h: d, fill: { color: fill } };
  opts.line = lineColor ? { color: lineColor, width: 1.5 } : { color: fill, width: 0 };
  slide.addShape(pres.shapes.OVAL, opts);
}
function hline(pres, slide, x1, y, x2, o) {
  const opts = { x: Math.min(x1, x2), y, w: Math.abs(x2 - x1), h: 0, line: { color: (o && o.color) || C.mint, width: (o && o.width) || 1.5 } };
  if (o && o.arrowStart) opts.line.beginArrowType = 'triangle';
  if (o && o.arrowEnd) opts.line.endArrowType = 'triangle';
  if (o && o.dash) opts.line.dashType = o.dash;
  slide.addShape(pres.shapes.LINE, opts);
}
function bullets(items, o) {
  // items: array of strings -> pptxgenjs bullet runs (bullet:true, breakLine on all but last)
  return items.map((t, i) => ({
    text: t,
    options: Object.assign(
      { bullet: true, breakLine: i < items.length - 1, paraSpaceAfter: (o && o.space) || 4, fontFace: FONT, lang: 'ar-SA' },
      (o && o.run) || {}
    ),
  }));
}
// Chrome shared by content slides: title (right), step pill (top-left), footer note (bottom-right).
function chrome(pres, slide, n, title, dark, titleSize) {
  slide.background = { color: dark ? C.teal : C.white };
  pill(pres, slide, 0.5, 0.45, 0.62, 0.34, n, dark ? { fill: C.mint, color: C.teal } : { fill: C.teal, color: C.white });
  text(slide, title, 1.3, 0.32, 8.2, 0.62, { fontSize: titleSize || 26, bold: true, color: dark ? C.white : C.teal, valign: 'middle' });
  text(slide, FOOTER, 3.5, 5.3, 6.0, 0.22, { fontSize: 8.5, color: dark ? C.mintLight : C.slate });
}

// ---------------------------------------------------------------- talk track (speaker notes)
const NOTES = {
  1: `[0:00–0:25]
السلام عليكم. نحن ${TEAM_NAME} من المدينة المنورة، ومشروعنا «هَوْنًا إلى الروضة».
كل يوم يصدر نحو 50,000 تصريح لزيارة الروضة الشريفة. الضيف يعرف موعده، ولا يعرف شيئاً بعده.
نحن نغطي ما بعده: من لحظة صدور التصريح حتى باب الروضة، بطبقة ميدانية صامتة تملكها الهيئة ولا تلمس نسك.
كل ما سترونه اليوم يعمل دون اتصال بالإنترنت.`,

  2: `[0:25–0:50]
الأرقام من نص التحدي نفسه: 50,000 تصريح يومياً، 48,000 زائر، ومتوسط انتظار 20 دقيقة قبل الدخول.
مساحة الروضة ثابتة، فلن نعد بتقصير الانتظار. المشكلة في نوعية الانتظار:
الضيف لا يعرف بوابته ولا نقطة تجمعه ولا كم بقي على دوره، ولا يفهم تعليمات الكوادر بلغته، فيتحول الانتظار إلى ترقب متوتر يدفع إلى التزاحم.
صوت الضيف في الملف الرسمي يقولها بكلماته: «وين نلاقي المسار الفوري؟»`,

  3: `[0:50–1:15]
هذه سيتي، 68 عاماً، إندونيسية، لا تتحدث العربية، ومعها تصريح نسك صحيح.
رحلتها اليوم ثلاث مراحل: الوصول عبر الساحات، الانتظار عند نقطة الفرز، ثم الدخول. وفي كل مرحلة مجهول: أين أذهب؟ متى دوري؟ ماذا يقول المشرف؟
والملف الرسمي يحدد سبباً مباشراً لنقاط الضغط: تفاوت سرعة التحقق من التصاريح، لأن التصريح يُقرأ 2 إلى 3 مرات في الطريق.
هذا هو الصندوق الأسود الذي نفتحه: ما بين رمز QR وباب الروضة.`,

  4: `[1:15–1:45]
الحل في مشهد واحد، أربع خطوات.
قبل 24 ساعة تصل رسالة الرحلة بلغة سيتي: البوابة ونقطة التجمع بالصور ووقت الانطلاق الذي يناسب كبار السن.
عند نقطة الفرز تحقق واحد فقط، ثم ختم صامت: تصريح فوج موقّع رقمياً يُتحقق منه دون اتصال في زمن ثابت.
في الانتظار بطاقة تعرض رقم فوجها ومدى زمنياً صادقاً وتعليمة المشرف مترجمة، وبطاقات «أرني» تحملها للموظف.
والمشرف يرسل نداءً صامتاً بضغطة واحدة إلى كل الهواتف والشاشات بعشر لغات، بلا مكبرات صوت.
كل هذا على محرك واحد داخل منظومة التفويج القائمة لدى الهيئة، ولا يلمس نسك.`,

  5: `[1:45–2:10]
أين الابتكار؟
أولاً: الطمأنة أداة لسلامة الحشود. لا نقصّر انتظاراً محكوماً بالطاقة الاستيعابية، بل نزيل المجهولات الثلاثة التي يحددها الملف سبباً للتدافع.
ثانياً: تحقق واحد وتحرك بالفوج، بدل تحققات متكررة متفاوتة السرعة.
ثالثاً: جسر لغوي صامت في الاتجاهين، من المشرف للضيف ومن الضيف للمشرف، بلا ترجمة فورية ولا نموذج لغوي وقت التشغيل.
رابعاً: محرك واحد وساعتان. ساعة الفوج الحية والتوأم الرقمي من الكود نفسه، فكل رقم نعرضه يمكن للجنة فحصه.`,

  6: `[2:10–2:50] العرض الحي، والحاسوب يبث نقطة اتصال محلية بلا إنترنت.
الهاتف الأول بالإندونيسية: تصل رسالة الرحلة لسيتي، بالصور والبوابة ونقطة التجمع.
عند نقطة الفرز أمسح تصريح نسك المحاكى، وهو معلن أنه محاكاة، مرة واحدة، فيظهر تصريح الفوج الموقّع على هاتفها ويُطبع ورقياً. أمسح الورقة بهاتف الموظف: تحقق دون اتصال في زمن ثابت.
بطاقة الانتظار: الفوج 14، نحو 12 إلى 18 دقيقة، والتعليمة الحالية «الرجاء الجلوس» بالإندونيسية مع رمز تصويري.
أضغط على الجهاز اللوحي «تقدموا بهدوء»، فتتغير الشاشة والهاتفان، بالإندونيسية والأردية، في الثانية نفسها، بصمت. وأرفع بطاقة «أرني»: «فقدت مجموعتي».
قبل 10 دقائق تظهر بطاقة التهيئة من محتوى الهيئة، ثم لا شيء على الشاشة داخل الروضة.`,

  7: `[2:50–3:20]
غرفة القرار ترى إشغال كل نقطة انتظار وتدفق التحقق وتنبيه التباطؤ، من أحداث الأفواج فقط، بلا كاميرات ولا بيانات شخصية.
والمحرك نفسه يشغّل التوأم الرقمي: يوم كامل من 50,000 تصريح، ثلاثة تحققات مقابل تحقق واحد مقابل نوافذ وصول متدرجة.
ما ترونه في الرسم أرقام توضيحية، لا نتيجة نهائية: التوأم يُعاير بقياسات ميدانية حقيقية من المسجد النبوي في المرحلة صفر، والأرقام تُقاس ولا تُفترض.
المهم أن الرقم يخرج من المحرك نفسه الذي شغّل الهاتف قبل دقيقة.`,

  8: `[3:20–3:45]
خطة التجربة مع الهيئة: نقطة انتظار واحدة، أسبوع واحد، فوج مقابل فوج، بمؤشرات معلنة مسبقاً.
وبصراحة: الحقيقي هو المحرك والتصريح الموقّع والنداء الصامت والمؤشرات والتوأم، كود يعمل ومختبَر.
المحاكاة المعلنة هي مصدر أوقات التصاريح خلف واجهة تكامل، وأزمنة المراحل قبل القياس الميداني.
وما يحتاج الهيئة: صياغة «موعدك محفوظ» وسياسة إعادة التفويج، ونصوص الآداب من منشوراتها فقط.
هذا نموذج أولي لهاكاثون، لا منتج رسمي للهيئة.`,

  9: `[3:45–4:00]
أنا عبدالعزيز حجار، طالب أمن سيبراني في جامعة الأمير مقرن بالمدينة المنورة، قدت فريق «رؤية بلس» في هاكاثون أمد 2026، ومعي فريق من 4 أعضاء بينهم عضوة تقود دراسة مسار النساء.
نقيم في المدينة، ونرصد نقاط الفرز يومياً، ونختبر النموذج مع الزوار في الساحات.
نحتاج من الهيئة ثلاثة أشياء: إذن رصد ميداني، نقطة انتظار واحدة لأسبوع، واعتماد صياغة الرسائل.
موعدك محفوظ، فامشِ إليه هونًا. شكراً لكم.

===== أسئلة متوقعة من اللجنة =====
1) هل تعتمدون على نسك؟
لا. التسجيل عبر ملصقات QR عند نقاط الانتظار وقوائم المشغلين وبطاقات الفنادق. الهيئة تملك الطبقة الميدانية وتجرّبها وحدها، والربط بنسك تكامل لاحق خلف واجهة PermitFeed، وهو محاكاة معلنة اليوم.
2) وجلال المكان؟
كل المحتوى ينتهي قبل الباب. لا صوت ولا أضواء ولا تلعيب. البطاقة تُعتم داخل الروضة. النصوص من منشورات الهيئة فقط. الحل يزيل مكبرات الصوت والحواجز الإضافية بدل أن يضيف أجهزة.
3) مسار النساء؟
عضوة في الفريق تقود دراسة مسار النساء: مقابلات وأزمنة منفصلة، وبطاقة «أريد موظفة» ضمن بطاقات «أرني»، ونقاط انتظار النساء تُقاس على حدة.
4) دقة الترجمة والمحتوى الشرعي؟
لا نموذج لغوي وقت التشغيل. حزم المحتوى موقّعة، والترجمات يراجعها متحدثون أصليون، ونصوص الآداب والتهيئة من الهيئة فقط، وأي إضافة تمر بمراجعة الهيئة والجهات الشرعية.
5) ماذا لو أعاد الأمن التحقق عند الباب؟
التصريح يدعم تحققاً سريعاً على مستوى الفوج: لون ورقم وتوقيع. والتوأم يحسب كلفة كل تحقق إضافي، فتقرر الهيئة بالأرقام لا بالرأي.
6) الاتصال والبطارية في الساحات؟
تطبيق ويب يعمل دون اتصال على نقطة اتصال محلية، تصريح ورقي، بطاقات «أرني» ورقية، شاشات نقاط الانتظار، وهاتف قائد المجموعة قناة ثانية.
7) البيانات الشخصية ونظام حماية البيانات (PDPL)؟
لا أسماء ولا جوازات ولا أرقام هواتف في النموذج. مرجع التصريح يُخزن مجزّأً بملح. التصريح الموقّع بلا بيانات شخصية. المؤشرات والتوأم على مستوى الفوج فقط، وسجل التدقيق متسلسل.
8) الجدول الزمني وحجم الفريق؟
المحرك يعيد استخدام هيكل «رفيق»: FastAPI، عزل الجلسات، سجل التدقيق، واجهة عربية بملف واحد. الإصدار 0 خلال أسبوعين قبل المعسكر الافتراضي، الإصدار 1 في المعسكر، والتجربة الميدانية في معسكر النموذج.`,
};

// ---------------------------------------------------------------- build
async function build() {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9'; // 10 x 5.625 in — set before any slide
  pres.author = TEAM_NAME;
  pres.title = 'هَوْنًا إلى الروضة، فكّر للحرمين 2026';
  pres.lang = 'ar-SA';

  slide1(pres);
  slide2(pres);
  slide3(pres);
  slide4(pres);
  slide5(pres);
  slide6(pres);
  slide7(pres);
  slide8(pres);
  slide9(pres);

  await pres.writeFile({ fileName: OUT_FILE });
  await postProcess(OUT_FILE);
  console.log('wrote', path.relative(process.cwd(), OUT_FILE));
}

// ---------------------------------------------------------------- slide 1: title
function slide1(pres) {
  const s = pres.addSlide();
  s.background = { color: C.teal };

  text(s, 'هَوْنًا إلى الروضة', 0.5, 0.85, 9.0, 1.0, { fontSize: 44, bold: true, color: C.white, valign: 'middle' });
  // English lockup, the only English on the deck, as the brand pill
  pill(pres, s, 7.55, 1.95, 1.95, 0.5, 'Hawnan', { fill: C.mint, color: C.teal, fontSize: 18, lang: 'en-US' });
  text(s, TAGLINE, 0.5, 2.65, 9.0, 0.6, { fontSize: 24, bold: true, color: C.gold, valign: 'middle' });
  text(s, TRACK_LINE, 4.0, 3.45, 5.5, 0.4, { fontSize: 14, color: C.white, valign: 'middle' });
  text(s, `${TEAM_NAME} · ${TEAM_HOME}`, 4.0, 3.9, 5.5, 0.35, { fontSize: 12, color: C.mintLight, valign: 'middle' });

  // Journey motif: four numbered steps (right to left) ending at the Rawdah ring
  text(s, 'رحلة الضيف من التصريح إلى باب الروضة', 0.5, 4.05, 3.6, 0.3, { fontSize: 10.5, color: C.mintLight, valign: 'middle' });
  const py = 4.5, pw = 0.62, ph = 0.4, gap = 0.22;
  const xs = [3.45, 3.45 - (pw + gap), 3.45 - 2 * (pw + gap), 3.45 - 3 * (pw + gap)];
  xs.forEach((x, i) => {
    pill(pres, s, x, py, pw, ph, i + 1, { fill: C.mint, color: C.teal, fontSize: 13 });
    if (i < xs.length - 1) hline(pres, s, x, py + ph / 2, x - gap, { color: C.mint, width: 1.5 });
  });
  const ringX = xs[3] - gap - 0.4;
  hline(pres, s, xs[3], py + ph / 2, ringX + 0.4, { color: C.gold, width: 1.5 });
  circle(pres, s, ringX, py, 0.4, C.teal, C.gold);
  text(s, 'الروضة', ringX - 0.3, py + ph + 0.05, 1.0, 0.25, { fontSize: 9, color: C.gold, align: 'center' });

  text(s, FOOTER, 3.5, 5.3, 6.0, 0.22, { fontSize: 8.5, color: C.mintLight });
  s.addNotes(NOTES[1]);
}

// ---------------------------------------------------------------- slide 2: problem in numbers
function slide2(pres) {
  const s = pres.addSlide();
  chrome(pres, s, 2, 'المشكلة بالأرقام');

  const stats = [
    { n: '50,000', label: 'تصريح يومياً لزيارة الروضة الشريفة', color: C.teal },
    { n: '48,000', label: 'زائر يومياً عبر الساحات ونقاط الفرز', color: C.teal },
    { n: '20', label: 'دقيقة متوسط الانتظار قبل الدخول', color: C.gold },
  ];
  const cw = 2.8, ch = 1.85, cy = 1.2;
  const cxs = [6.7, 3.6, 0.5]; // RTL: first stat on the right
  stats.forEach((st, i) => {
    card(pres, s, cxs[i], cy, cw, ch, { fill: C.mintPale });
    text(s, st.n, cxs[i] + 0.15, cy + 0.15, cw - 0.3, 0.95, { fontSize: 46, bold: true, color: st.color, align: 'center', valign: 'middle', lang: 'en-US', rtlMode: false });
    text(s, st.label, cxs[i] + 0.2, cy + 1.12, cw - 0.4, 0.6, { fontSize: 12.5, color: C.slate, align: 'center', valign: 'top' });
  });
  text(s, 'المصدر: نص التحدي الرسمي، فكّر للحرمين 2026. مساحة الروضة ثابتة (نحو 330 م²)، فالانتظار لا يُلغى، لكنه يُفهم.', 0.5, 3.15, 9.0, 0.3, { fontSize: 10, color: C.slate });

  // Guest quote from the brief
  card(pres, s, 0.5, 3.6, 9.0, 1.0, { fill: C.teal });
  text(s, '«وين نلاقي المسار الفوري؟»', 0.8, 3.68, 8.4, 0.55, { fontSize: 20, bold: true, color: C.white, valign: 'middle' });
  text(s, 'صوت الضيف، من الملف الرسمي للتحدي: حجز خاطئ للجنس، قوائم انتظار، حجز الأسرة تحت حساب واحد، «وين نلاقي المسار الفوري»', 0.8, 4.22, 8.4, 0.3, { fontSize: 10, color: C.mintLight });

  runs(s, [
    { text: 'الضيف يعرف موعده، ', options: { fontSize: 15, color: C.slate } },
    { text: 'ولا يعرف شيئاً بعده.', options: { fontSize: 15, bold: true, color: C.teal } },
  ], 0.5, 4.75, 9.0, 0.45, { valign: 'middle' });
  s.addNotes(NOTES[2]);
}

// ---------------------------------------------------------------- slide 3: the black box
function slide3(pres) {
  const s = pres.addSlide();
  chrome(pres, s, 3, 'الصندوق الأسود: رحلة سيتي اليوم');
  text(s, 'سيتي، 68 عاماً، إندونيسية، لا تتحدث العربية، معها تصريح نسك صحيح ولا تعرف ماذا بعده.', 0.5, 0.98, 9.0, 0.35, { fontSize: 13, color: C.slate, valign: 'middle' });

  // The box itself
  card(pres, s, 0.5, 1.45, 9.0, 2.95, { fill: C.slate, radius: 0.18 });
  text(s, 'الصندوق الأسود: من رمز QR إلى باب الروضة', 0.8, 1.55, 8.4, 0.3, { fontSize: 11, bold: true, color: C.mintLight, valign: 'middle' });

  const steps = [
    { name: 'الوصول عبر الساحات', q: 'أين أذهب؟', d: 'لا بوابة معلومة ولا نقطة تجمع، والمسار من الفندق غير مرسوم' },
    { name: 'الانتظار عند نقطة الفرز', q: 'متى دوري؟', d: 'التصريح يُقرأ 2 إلى 3 مرات، والانتظار مفتوح بلا مدى زمني' },
    { name: 'الدخول', q: 'ماذا يقول المشرف؟', d: 'تعليمات بمكبر صوت بلغة لا تفهمها، فتتبع الحشد' },
  ];
  const cw = 2.5, ch = 0.85, cy = 2.05;
  const cxs = [6.6, 3.75, 0.9];
  steps.forEach((st, i) => {
    const x = cxs[i];
    card(pres, s, x, cy, cw, ch, { fill: C.white, radius: 0.12 });
    pill(pres, s, x + cw / 2 - 0.3, cy - 0.17, 0.6, 0.32, i + 1, { fill: C.mint, color: C.teal, fontSize: 12 });
    text(s, st.name, x + 0.15, cy + 0.2, cw - 0.3, 0.55, { fontSize: 14, bold: true, color: C.teal, align: 'center', valign: 'middle' });
    text(s, st.q, x, cy + ch + 0.18, cw, 0.4, { fontSize: 16, bold: true, color: C.white, align: 'center', valign: 'middle' });
    text(s, st.d, x + 0.1, cy + ch + 0.6, cw - 0.2, 0.7, { fontSize: 10.5, color: C.mintLight, align: 'center' });
    if (i < steps.length - 1) hline(pres, s, x, cy + ch / 2, cxs[i + 1] + cw, { color: C.mint, width: 2, arrowStart: true });
  });

  runs(s, [
    { text: 'ثلاثة مجهولات', options: { fontSize: 14, bold: true, color: C.gold } },
    { text: ' تحوّل الانتظار إلى ترقب متوتر يدفع إلى التزاحم، والملف الرسمي يسمّي تفاوت سرعة التحقق سبباً مباشراً لنقاط الضغط.', options: { fontSize: 14, color: C.slate } },
  ], 0.5, 4.55, 9.0, 0.6, { valign: 'middle' });
  s.addNotes(NOTES[3]);
}

// ---------------------------------------------------------------- slide 4: the solution in one scene
function slide4(pres) {
  const s = pres.addSlide();
  chrome(pres, s, 4, 'الحل في مشهد واحد');

  const steps = [
    { t: 'رسالة الرحلة', d: 'بلغة الضيف قبل 24 ساعة ثم 90 ثم 30 دقيقة: البوابة ونقطة التجمع بالصور ووقت الانطلاق.' },
    { t: 'تحقق واحد + ختم صامت', d: 'يُقرأ تصريح نسك مرة واحدة، فيصدر تصريح فوج موقّع يُتحقق منه دون اتصال في زمن ثابت.' },
    { t: 'بطاقة الانتظار', d: 'رقم الفوج، مدى زمني صادق «نحو 12–18 دقيقة»، تعليمة المشرف مترجمة، وبطاقات «أرني».' },
    { t: 'النداء الصامت', d: 'ضغطة واحدة من المشرف تصل إلى الهواتف والشاشات بعشر لغات، بلا مكبرات صوت.' },
  ];
  const cw = 2.1, gap = 0.2;
  const xs = [W - 0.5 - cw, W - 0.5 - 2 * cw - gap, W - 0.5 - 3 * cw - 2 * gap, W - 0.5 - 4 * cw - 3 * gap];
  const py = 1.25, pw = 0.8, ph = 0.42;
  // connector under all four pills first, pills drawn on top
  hline(pres, s, xs[0] + cw / 2, py + ph / 2, xs[3] + cw / 2, { color: C.mint, width: 1.5 });
  steps.forEach((st, i) => {
    const x = xs[i];
    pill(pres, s, x + cw / 2 - pw / 2, py, pw, ph, i + 1, { fill: C.teal, color: C.white, fontSize: 14 });
    text(s, st.t, x - 0.05, py + 0.6, cw + 0.1, 0.5, { fontSize: 13.5, bold: true, color: C.teal, align: 'center', valign: 'middle' });
    text(s, st.d, x + 0.05, py + 1.15, cw - 0.1, 1.35, { fontSize: 11.5, color: C.slate, align: 'center' });
  });

  card(pres, s, 0.5, 4.0, 9.0, 1.1, { fill: C.mintPale });
  runs(s, [
    { text: 'خلف المشهد: ', options: { fontSize: 12.5, bold: true, color: C.teal } },
    { text: 'محرك تفويج واحد يشغّل ساعة الفوج الحية والتوأم الرقمي من الكود نفسه، داخل منظومة التفويج القائمة لدى الهيئة. ', options: { fontSize: 12.5, color: C.slate } },
    { text: 'لا يلمس نسك', options: { fontSize: 12.5, bold: true, color: C.gold } },
    { text: '، ويبدأ حيث يتوقف رمز QR وينتهي عند باب الروضة. لا شيء على الشاشة داخل الروضة.', options: { fontSize: 12.5, color: C.slate } },
  ], 0.8, 4.12, 8.4, 0.86, { valign: 'middle' });
  s.addNotes(NOTES[4]);
}

// ---------------------------------------------------------------- slide 5: four innovations
function slide5(pres) {
  const s = pres.addSlide();
  chrome(pres, s, 5, 'الابتكارات الأربعة');

  const items = [
    { t: 'الطمأنة أداة لسلامة الحشود', d: 'لا نقصّر انتظاراً محكوماً بالطاقة الاستيعابية، بل نزيل المجهولات الثلاثة التي يحددها الملف سبباً للتدافع.', icon: 'heart' },
    { t: 'تحقق واحد وتحرك بالفوج', d: 'تصريح فوج موقّع يُقرأ في زمن ثابت بدل تحققات متكررة متفاوتة السرعة عند كل نقطة.', icon: 'one' },
    { t: 'جسر لغوي صامت في الاتجاهين', d: 'نداء صامت من المشرف للضيف، وبطاقات «أرني» من الضيف للمشرف، بلا ترجمة فورية ولا نموذج لغوي وقت التشغيل.', icon: 'arrow' },
    { t: 'محرك واحد وساعتان', d: 'ساعة الفوج الحية والتوأم الرقمي من الكود نفسه، فكل رقم في العرض يخرج من محرك ', icon: 'gear', tail: 'يمكن للجنة فحصه.' },
  ];
  const cw = 4.35, ch = 1.8, gapY = 0.25;
  const pos = [
    [5.15, 1.15], [0.5, 1.15],
    [5.15, 1.15 + ch + gapY], [0.5, 1.15 + ch + gapY],
  ];
  items.forEach((it, i) => {
    const [x, y] = pos[i];
    card(pres, s, x, y, cw, ch, { fill: C.mintPale });
    const d = 0.72, ix = x + cw - 0.2 - d, iy = y + 0.22;
    circle(pres, s, ix, iy, d, C.mint);
    if (it.icon === 'heart') s.addShape(pres.shapes.HEART, { x: ix + 0.18, y: iy + 0.2, w: 0.36, h: 0.32, fill: { color: C.white }, line: { color: C.white, width: 0 } });
    if (it.icon === 'one') text(s, '1', ix, iy, d, d, { fontSize: 22, bold: true, color: C.white, align: 'center', valign: 'middle', lang: 'en-US', rtlMode: false });
    if (it.icon === 'arrow') s.addShape(pres.shapes.LEFT_RIGHT_ARROW, { x: ix + 0.13, y: iy + 0.24, w: 0.46, h: 0.24, fill: { color: C.white }, line: { color: C.white, width: 0 } });
    if (it.icon === 'gear') s.addShape(pres.shapes.GEAR_6, { x: ix + 0.17, y: iy + 0.17, w: 0.38, h: 0.38, fill: { color: C.white }, line: { color: C.white, width: 0 } });
    text(s, it.t, x + 0.2, y + 0.22, cw - d - 0.55, 0.72, { fontSize: 15, bold: true, color: C.teal, valign: 'middle' });
    const parts = [{ text: it.d, options: { fontSize: 11.5, color: C.slate } }];
    if (it.tail) parts.push({ text: it.tail, options: { fontSize: 11.5, bold: true, color: C.gold } });
    runs(s, parts, x + 0.2, y + 1.02, cw - 0.4, 0.7, {});
  });
  s.addNotes(NOTES[5]);
}

// ---------------------------------------------------------------- slide 6: live demo
function phoneFrame(pres, s, x, y, w, h) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.22, fill: { color: C.ink }, line: { color: C.ink, width: 0 }, shadow: shadow() });
  const sx = x + 0.09, sy = y + 0.26, sw = w - 0.18, sh = h - 0.5;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: sx, y: sy, w: sw, h: sh, rectRadius: 0.1, fill: { color: C.white }, line: { color: C.white, width: 0 } });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + w / 2 - 0.25, y: y + 0.1, w: 0.5, h: 0.08, rectRadius: 0.04, fill: { color: C.slate }, line: { color: C.slate, width: 0 } });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + w / 2 - 0.3, y: y + h - 0.16, w: 0.6, h: 0.06, rectRadius: 0.03, fill: { color: C.slate }, line: { color: C.slate, width: 0 } });
  return { sx, sy, sw, sh };
}
function tabletFrame(pres, s, x, y, w, h) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.16, fill: { color: C.ink }, line: { color: C.ink, width: 0 }, shadow: shadow() });
  const sx = x + 0.16, sy = y + 0.14, sw = w - 0.32, sh = h - 0.28;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: sx, y: sy, w: sw, h: sh, rectRadius: 0.06, fill: { color: C.white }, line: { color: C.white, width: 0 } });
  circle(pres, s, x + w - 0.11, y + h / 2 - 0.04, 0.08, C.slate);
  return { sx, sy, sw, sh };
}
function slide6(pres) {
  const s = pres.addSlide();
  chrome(pres, s, 6, 'العرض الحي: هاتفان وجهاز لوحي وشاشة');
  pill(pres, s, 0.5, 0.95, 1.7, 0.36, 'يعمل دون اتصال', { fill: C.white, color: C.teal, line: C.gold, lineWidth: 1.5, fontSize: 11 });
  text(s, 'الحاسوب يبث نقطة اتصال محلية ولا إنترنت في العرض. الشاشة والهواتف تتغير في الثانية نفسها، بصمت.', 2.4, 0.95, 7.1, 0.36, { fontSize: 11, color: C.slate, valign: 'middle' });

  const fy = 1.5, fh = 3.35, pw = 1.95;
  // Phone A (right): Indonesian guest
  const a = phoneFrame(pres, s, 7.45, fy, pw, fh);
  if (fs.existsSync(SCREENSHOTS.guestId)) {
    s.addImage({ path: SCREENSHOTS.guestId, x: a.sx, y: a.sy, w: a.sw, h: a.sh, sizing: { type: 'contain', w: a.sw, h: a.sh } });
  } else {
    guestScreenId(pres, s, a);
  }
  // Phone B (middle): Urdu guest
  const b = phoneFrame(pres, s, 5.15, fy, pw, fh);
  if (fs.existsSync(SCREENSHOTS.guestUr)) {
    s.addImage({ path: SCREENSHOTS.guestUr, x: b.sx, y: b.sy, w: b.sw, h: b.sh, sizing: { type: 'contain', w: b.sw, h: b.sh } });
  } else {
    guestScreenUr(pres, s, b);
  }
  // Staff tablet (left), landscape
  const t = tabletFrame(pres, s, 0.5, fy + 0.35, 4.25, 2.65);
  if (fs.existsSync(SCREENSHOTS.staff)) {
    s.addImage({ path: SCREENSHOTS.staff, x: t.sx, y: t.sy, w: t.sw, h: t.sh, sizing: { type: 'contain', w: t.sw, h: t.sh } });
  } else {
    staffScreen(pres, s, t);
  }

  const ly = fy + fh + 0.08;
  text(s, 'هاتف الضيفة، بالإندونيسية', 7.2, ly, 2.45, 0.3, { fontSize: 10.5, bold: true, color: C.teal, align: 'center' });
  text(s, 'هاتف ضيف، بالأردية', 4.9, ly, 2.45, 0.3, { fontSize: 10.5, bold: true, color: C.teal, align: 'center' });
  text(s, 'جهاز المشرف اللوحي: النداء الصامت', 0.5, ly, 4.25, 0.3, { fontSize: 10.5, bold: true, color: C.teal, align: 'center' });
  s.addNotes(NOTES[6]);
}
function guestScreenId(pres, s, f) {
  const { sx, sy, sw } = f;
  pill(pres, s, sx + 0.12, sy + 0.12, sw - 0.24, 0.3, 'Rombongan 14', { fill: C.teal, color: C.white, fontSize: 10, lang: 'id-ID' });
  textLtr(s, 'Titik tunggu B2 · Perempuan 08:20', sx + 0.12, sy + 0.5, sw - 0.24, 0.25, { fontSize: 7.5, color: C.slate, lang: 'id-ID' });
  textLtr(s, 'sekitar', sx + 0.12, sy + 0.8, sw - 0.24, 0.22, { fontSize: 8, color: C.slate, lang: 'id-ID', align: 'center' });
  textLtr(s, '12–18', sx + 0.12, sy + 1.0, sw - 0.24, 0.5, { fontSize: 26, bold: true, color: C.teal, align: 'center', valign: 'middle' });
  textLtr(s, 'menit', sx + 0.12, sy + 1.5, sw - 0.24, 0.22, { fontSize: 8, color: C.slate, lang: 'id-ID', align: 'center' });
  card(pres, s, sx + 0.12, sy + 1.8, sw - 0.24, 0.62, { fill: C.mintPale, radius: 0.08 });
  circle(pres, s, sx + 0.2, sy + 1.93, 0.36, C.mint);
  textLtr(s, 'Instruksi petugas', sx + 0.62, sy + 1.86, sw - 0.76, 0.2, { fontSize: 6.5, color: C.slate, lang: 'id-ID' });
  textLtr(s, 'Silakan duduk', sx + 0.62, sy + 2.05, sw - 0.76, 0.3, { fontSize: 10, bold: true, color: C.teal, lang: 'id-ID' });
  pill(pres, s, sx + 0.12, sy + 2.52, sw - 0.24, 0.27, 'Tunjukkan ke petugas', { fill: C.white, color: C.teal, line: C.teal, lineWidth: 1, fontSize: 7.5, lang: 'id-ID', bold: false });
}
function guestScreenUr(pres, s, f) {
  const { sx, sy, sw } = f;
  pill(pres, s, sx + 0.12, sy + 0.12, sw - 0.24, 0.3, 'گروپ 14', { fill: C.teal, color: C.white, fontSize: 10, lang: 'ur-PK' });
  text(s, 'انتظار کا مقام B2 · خواتین 08:20', sx + 0.12, sy + 0.5, sw - 0.24, 0.25, { fontSize: 7.5, color: C.slate, lang: 'ur-PK' });
  text(s, 'تقریباً', sx + 0.12, sy + 0.8, sw - 0.24, 0.22, { fontSize: 8, color: C.slate, lang: 'ur-PK', align: 'center' });
  textLtr(s, '12–18', sx + 0.12, sy + 1.0, sw - 0.24, 0.5, { fontSize: 26, bold: true, color: C.teal, align: 'center', valign: 'middle' });
  text(s, 'منٹ', sx + 0.12, sy + 1.5, sw - 0.24, 0.22, { fontSize: 8, color: C.slate, lang: 'ur-PK', align: 'center' });
  card(pres, s, sx + 0.12, sy + 1.8, sw - 0.24, 0.62, { fill: C.mintPale, radius: 0.08 });
  circle(pres, s, sx + sw - 0.56, sy + 1.93, 0.36, C.mint);
  text(s, 'عملے کی ہدایت', sx + 0.14, sy + 1.86, sw - 0.76, 0.2, { fontSize: 6.5, color: C.slate, lang: 'ur-PK' });
  text(s, 'براہ کرم بیٹھ جائیں', sx + 0.14, sy + 2.05, sw - 0.76, 0.3, { fontSize: 10, bold: true, color: C.teal, lang: 'ur-PK' });
  pill(pres, s, sx + 0.12, sy + 2.52, sw - 0.24, 0.27, 'عملے کو دکھائیں', { fill: C.white, color: C.teal, line: C.teal, lineWidth: 1, fontSize: 7.5, lang: 'ur-PK', bold: false });
}
function staffScreen(pres, s, f) {
  const { sx, sy, sw, sh } = f;
  text(s, 'نقطة الانتظار B2 · الفوج 14 · تعليمة نشطة واحدة', sx + 0.15, sy + 0.1, sw - 0.3, 0.3, { fontSize: 9.5, bold: true, color: C.teal, valign: 'middle' });
  const labels = ['الرجاء الجلوس', 'تقدموا بهدوء', 'انتظروا هنا', 'الفوج التالي بعد 5 دقائق'];
  const bw = (sw - 0.45) / 2, bh = 0.62;
  const bx = [sx + sw - 0.15 - bw, sx + 0.15];
  labels.forEach((l, i) => {
    const x = bx[i % 2], y = sy + 0.5 + Math.floor(i / 2) * (bh + 0.15);
    const active = i === 0;
    pill(pres, s, x, y, bw, bh, l, active
      ? { fill: C.teal, color: C.white, fontSize: 10.5 }
      : { fill: C.white, color: C.teal, line: C.mint, lineWidth: 1.25, fontSize: 10.5, bold: false });
  });
  text(s, 'ضغطة واحدة = التعليمة نفسها بعشر لغات على الهواتف والشاشة، وكل بث في سجل التدقيق.', sx + 0.15, sy + sh - 0.45, sw - 0.3, 0.38, { fontSize: 8, color: C.slate, valign: 'middle' });
}

// ---------------------------------------------------------------- slide 7: twin and indicators
function slide7(pres) {
  const s = pres.addSlide();
  chrome(pres, s, 7, 'التوأم الرقمي والمؤشرات');

  // Chart (right half): illustrative index values, replaced by calibrated twin output
  s.addChart(pres.charts.BAR, [
    { name: 'مؤشر أحداث الضغط', labels: ['3 تحققات', 'تحقق واحد', 'نوافذ متدرجة'], values: [100, 55, 38] },
  ], {
    x: 4.4, y: 1.05, w: 5.1, h: 3.35,
    barDir: 'col',
    barGapWidthPct: 70,
    chartColors: [C.teal],
    showTitle: true,
    title: 'مؤشر أحداث الضغط عند نقاط الفرز (الأساس = 100)',
    titleFontFace: FONT, titleFontSize: 12, titleColor: C.teal,
    showLegend: false,
    showValue: true, dataLabelPosition: 'outEnd', dataLabelFontFace: FONT, dataLabelFontSize: 12, dataLabelFontBold: true, dataLabelColor: C.ink,
    catAxisLabelFontFace: FONT, catAxisLabelFontSize: 11, catAxisLabelColor: C.slate,
    valAxisLabelFontFace: FONT, valAxisLabelFontSize: 9, valAxisLabelColor: C.slate,
    valAxisMinVal: 0, valAxisMaxVal: 120, valAxisMajorUnit: 30,
    valGridLine: { color: C.grid, size: 0.5 },
    catGridLine: { style: 'none' },
    valAxisLineShow: false,
    catAxisLineShow: true,
  });
  text(s, 'نتائج محاكاة توضيحية، تُستبدل بأرقام التوأم المعاير بقياسات ميدانية من المسجد النبوي.', 4.4, 4.45, 5.1, 0.3, { fontSize: 9.5, color: C.slate, align: 'center', valign: 'middle' });

  // KPI table (left): columns reversed so the first column reads on the right
  text(s, 'المؤشرات الثلاثة', 0.5, 1.05, 3.6, 0.35, { fontSize: 14, bold: true, color: C.teal, valign: 'middle' });
  const hdr = (t) => ({ text: t, options: { bold: true, color: C.white, fill: { color: C.teal }, fontFace: FONT, fontSize: 10, align: 'right', rtlMode: true, lang: 'ar-SA', valign: 'middle', margin: 0.05 } });
  const cell = (t, o) => ({ text: t, options: Object.assign({ color: C.ink, fill: { color: C.white }, fontFace: FONT, fontSize: 10, align: 'right', rtlMode: true, lang: 'ar-SA', valign: 'middle', margin: 0.05 }, o || {}) });
  // numeric target cells are LTR: in an RTL paragraph "≥" would be mirrored into "≤"
  const num = (t) => cell(t, { bold: true, color: C.teal, align: 'center', rtlMode: false, lang: 'en-US' });
  s.addTable([
    [hdr('الهدف'), hdr('الأساس'), hdr('المؤشر')],
    [num('≥ 90%'), cell('غير مقاس'), cell('ضيوف يعرفون البوابة ونقطة التجمع قبل الوصول')],
    [num('1'), cell('2–3، يُقاس ميدانياً'), cell('مرات التحقق لكل ضيف')],
    [num('−50%'), cell('يُقاس ميدانياً'), cell('تباين سرعة التحقق عند الممرات')],
  ], {
    x: 0.5, y: 1.45, w: 3.6, colW: [0.8, 1.05, 1.75], rowH: [0.34, 0.5, 0.5, 0.5],
    border: { type: 'solid', color: C.grid, pt: 0.75 },
    fontFace: FONT,
  });
  text(s, 'المؤشرات تُشتق من أحداث الأفواج فقط: لا كاميرات ولا تتبع أفراد. غرفة القرار ترى إشغال كل نقطة انتظار، وتدفق التحقق لكل مسار، وتنبيه التباطؤ الفوري.', 0.5, 3.45, 3.6, 1.1, { fontSize: 10.5, color: C.slate });
  s.addNotes(NOTES[7]);
}

// ---------------------------------------------------------------- slide 8: pilot and honesty
function slide8(pres) {
  const s = pres.addSlide();
  chrome(pres, s, 8, 'التجربة مع الهيئة: ما هو حقيقي وما هو محاكاة', false, 24);

  const plan = ['نقطة انتظار واحدة', 'أسبوع، فوج مقابل فوج', 'مؤشرات معلنة قبل البدء'];
  const iw = 2.9, ixs = [6.6, 3.55, 0.5];
  plan.forEach((p, i) => {
    const x = ixs[i];
    pill(pres, s, x + iw - 0.55, 1.08, 0.55, 0.34, i + 1, { fill: C.teal, color: C.white, fontSize: 12 });
    text(s, p, x, 1.06, iw - 0.68, 0.38, { fontSize: 12.5, bold: true, color: C.teal, valign: 'middle' });
  });

  const cols = [
    {
      h: 'حقيقي', x: 6.65, fill: C.teal, hc: C.white, tc: C.white,
      items: ['محرك ساعة الفوج وتقدير المدى الزمني', 'التصريح الموقّع والتحقق منه دون اتصال', 'النداء الصامت وبطاقات «أرني» وبطاقة التهيئة', 'المؤشرات والتوأم الرقمي', 'كود يعمل ومختبَر'],
    },
    {
      h: 'محاكاة معلنة', x: 3.575, fill: C.mintLight, hc: C.teal, tc: C.ink,
      items: ['مصدر أوقات التصاريح واللغة (نسك) خلف واجهة تكامل', 'أزمنة المراحل ونسب التدفق قبل القياس الميداني', 'بيانات التصاريح في النموذج الأولي', 'أرقام الأثر في هذا العرض حتى تُقاس'],
    },
    {
      h: 'يحتاج الهيئة', x: 0.5, fill: C.white, hc: C.teal, tc: C.slate, line: C.gold,
      items: ['صياغة «موعدك محفوظ» وسياسة إعادة التفويج للمتأخرين', 'نصوص الآداب والتهيئة من منشورات الهيئة فقط', 'إذن الرصد الميداني ونقطة انتظار للتجربة', 'ربط لاحق بمصدر أوقات التصاريح'],
    },
  ];
  const cw = 2.85, cy = 1.65, ch = 3.4;
  cols.forEach((c) => {
    card(pres, s, c.x, cy, cw, ch, { fill: c.fill, line: c.line, lineWidth: 1.5, radius: 0.14 });
    text(s, c.h, c.x + 0.2, cy + 0.15, cw - 0.4, 0.45, { fontSize: 16, bold: true, color: c.hc, valign: 'middle' });
    s.addText(bullets(c.items, { space: 7, run: { fontSize: 12, color: c.tc } }), Object.assign({ x: c.x + 0.2, y: cy + 0.7, w: cw - 0.4, h: ch - 0.9 }, ar({})));
  });
  s.addNotes(NOTES[8]);
}

// ---------------------------------------------------------------- slide 9: team and next step
function slide9(pres) {
  const s = pres.addSlide();
  chrome(pres, s, 9, 'الفريق والخطوة التالية', true);

  runs(s, [
    { text: 'عبدالعزيز أحمد حجار، قائد الفريق: ', options: { fontSize: 13, bold: true, color: C.white } },
    { text: 'طالب أمن سيبراني في جامعة الأمير مقرن بالمدينة المنورة، قاد فريق «رؤية بلس» في هاكاثون أمد 2026 وبنى «رفيق» بـ 29 واجهة برمجية و89 اختباراً وواجهة عربية تعمل دون اتصال.', options: { fontSize: 13, color: C.white } },
  ], 0.5, 1.0, 9.0, 0.8, { valign: 'top' });

  // Right column: roles
  text(s, 'الفريق: 4 أعضاء', 5.0, 1.95, 4.5, 0.35, { fontSize: 13, bold: true, color: C.mintLight, valign: 'middle' });
  const roles = ['واجهات وتجربة مستخدم', 'رصد ميداني في مسار النساء ومقابلات الزائرات', 'محتوى شرعي وتاريخي ولغات', 'بحث ميداني وبيانات للتوأم الرقمي'];
  roles.forEach((r, i) => {
    const y = 2.35 + i * 0.44;
    pill(pres, s, 9.5 - 0.5, y, 0.5, 0.32, i + 1, { fill: C.mint, color: C.teal, fontSize: 11 });
    text(s, r, 5.0, y - 0.02, 3.85, 0.36, { fontSize: 12, color: C.white, valign: 'middle' });
  });
  text(s, 'ميزة الفريق: نقيم في المدينة المنورة، نرصد نقاط الفرز يومياً ونختبر النموذج مع الزوار في الساحات.', 5.0, 4.12, 4.5, 0.5, { fontSize: 10.5, color: C.mintLight });

  // Left column: what we need from the Authority
  card(pres, s, 0.5, 1.95, 4.1, 2.7, { fill: C.white, radius: 0.14 });
  text(s, 'ما نحتاجه من الهيئة', 0.7, 2.08, 3.7, 0.4, { fontSize: 14, bold: true, color: C.teal, valign: 'middle' });
  const needs = ['إذن رصد ميداني في ساحات المسجد النبوي', 'نقطة انتظار واحدة لمدة أسبوع، فوج مقابل فوج', 'اعتماد صياغة رسائل الطمأنة وسياسة إعادة التفويج'];
  needs.forEach((n, i) => {
    const y = 2.6 + i * 0.62;
    pill(pres, s, 4.4 - 0.5, y, 0.5, 0.32, i + 1, { fill: C.teal, color: C.white, fontSize: 11 });
    text(s, n, 0.7, y - 0.06, 3.1, 0.5, { fontSize: 11.5, color: C.slate, valign: 'middle' });
  });

  text(s, TAGLINE, 0.5, 4.72, 9.0, 0.5, { fontSize: 22, bold: true, color: C.gold, valign: 'middle' });
  s.addNotes(NOTES[9]);
}

// ---------------------------------------------------------------- post-process (two small OOXML touches)
// 1) Gold bar: pptxgenjs colours a single series with one colour; PowerPoint allows per-point colour
//    through <c:dPt>. We insert one dPt (index 2, "نوافذ متدرجة") right after <c:invertIfNegative/>,
//    where the schema places it.
// 2) Notes paragraphs: addNotes() writes the whole note as one run with raw newlines. PowerPoint does
//    not treat those as breaks, so each line becomes its own right-to-left paragraph.
async function postProcess(file) {
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const names = Object.keys(zip.files);

  for (const name of names.filter((n) => /^ppt\/charts\/chart\d+\.xml$/.test(n))) {
    let xml = await zip.file(name).async('string');
    const marker = '<c:invertIfNegative val="0"/>';
    if (!xml.includes(marker) || xml.includes('<c:dPt>')) continue;
    const dPt = `<c:dPt><c:idx val="2"/><c:invertIfNegative val="0"/><c:bubble3D val="0"/><c:spPr><a:solidFill><a:srgbClr val="${C.gold}"/></a:solidFill></c:spPr></c:dPt>`;
    xml = xml.replace(marker, marker + dPt); // first series only
    zip.file(name, xml);
  }

  for (const name of names.filter((n) => /^ppt\/notesSlides\/notesSlide\d+\.xml$/.test(n))) {
    let xml = await zip.file(name).async('string');
    // pptxgenjs writes the note as one run: <a:p><a:r><a:rPr lang="en-US" dirty="0"/><a:t>...</a:t></a:r>...</a:p>
    const re = /<a:p><a:r><a:rPr lang="en-US" dirty="0"\/><a:t>([\s\S]*?)<\/a:t><\/a:r>/;
    const m = xml.match(re);
    if (!m || !/\r?\n/.test(m[1])) continue;
    const lines = m[1].split(/\r?\n/);
    const rPr = `<a:rPr lang="ar-SA" altLang="en-US" sz="1400" dirty="0"><a:latin typeface="${FONT}"/><a:cs typeface="${FONT}"/></a:rPr>`;
    const para = (line) => (line.length ? `<a:pPr rtl="1" algn="r"/><a:r>${rPr}<a:t>${line}</a:t></a:r>` : '<a:pPr rtl="1" algn="r"/>');
    // every line but the last becomes a closed paragraph; the last one keeps the original paragraph tail
    const head = lines.slice(0, -1).map((l) => `<a:p>${para(l)}</a:p>`).join('');
    xml = xml.replace(re, head + '<a:p>' + para(lines[lines.length - 1]));
    zip.file(name, xml);
  }

  const buf = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  fs.writeFileSync(file, buf);
}

build().catch((err) => {
  console.error(err);
  process.exit(1);
});
