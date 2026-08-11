// config.js — константы и «словари» приложения.
// Чистый модуль без состояния и DOM: только данные.
// Импортируется всеми остальными модулями.

// ── MediaPipe: CDN + эталонная модель ──
export const CDN = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18";
export const MODEL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task";

// Индексы 33 точек MediaPipe Pose.
export const I = { NOSE:0, LEI:1, LEYE:2, LEO:3, REI:4, REYE:5, REO:6, LEA:7, REA:8,
            LMO:9, RMO:10, LSH:11, RSH:12, LEL:13, REL:14, LWR:15, RWR:16,
            LHIP:23, RHIP:24, LKN:25, RKN:26, LAN:27, RAN:28, LHE:29, RHE:30, LFI:31, RFI:32 };

// «Костные» связи по частям тела (для отрисовки полного скелета).
export const GROUPS = {
  head:  [[I.NOSE,I.LEI],[I.LEI,I.LEYE],[I.LEYE,I.LEO],[I.LEO,I.LEA],
          [I.NOSE,I.REI],[I.REI,I.REYE],[I.REYE,I.REO],[I.REO,I.REA],[I.LMO,I.RMO]],
  torso: [[I.LSH,I.RSH],[I.LSH,I.LHIP],[I.RSH,I.RHIP],[I.LHIP,I.RHIP]],
  arms:  [[I.LSH,I.LEL],[I.LEL,I.LWR],[I.RSH,I.REL],[I.REL,I.RWR]],
  legs:  [[I.LHIP,I.LKN],[I.LKN,I.LAN],[I.RHIP,I.RKN],[I.RKN,I.RAN],
          [I.LHIP,I.LHE],[I.LHE,I.LFI],[I.RHIP,I.RHE],[I.RHE,I.RFI]]
};

// Пороги видимости: меньше VIS_LO — точка «невидима», дальше к 1 — прозрачность растёт.
export const VIS_LO = 0.15, VIS_SPAN = 0.6;

// Сглаживание: порог «телепорта» — скачок больше этой величины (в координатах
// массива: доли кадра для 2D, метры для worldLandmarks) берётся сырым, без смешивания.
export const SMOOTH_TELEPORT = 0.15;

// Вес оси z (глубины) в расчёте углов: 1 — полное 3D, меньше — приглушить шумную
// глубину на камере (0.7 если в лайве z гуляет слишком сильно).
export const ANGLE_Z_W = 1.0;

// Минимальная рассинхронизированная корреляция «формы движения» (форма-гейт).
export const SYNC_MIN = 0.78;
// Размах A, ниже которого фича считается почти-статичной → форма-гейт её не трогает
// (иначе корреляция двух «шумовых» рядов случайно гуляет вокруг порога и зануляет
// честные фичи: одинаковые видео давали кап ~74% вместо 100%).
export const SYNC_STATIC_RNG = 15;

// Максимум игрового счёта и порог ниже которого фича считается «застывшей».
export const TIER_MAX = 10000;
export const STATIC_RANGE = 1.5;

// Тиры: как интерпретировать сходство кадра.
export const TIERS = [
  { min:0.85, name:"ОТЛИЧНО", col:"#c6ff2e" },
  { min:0.70, name:"ХОРОШО",  col:"#7ae0a0" },
  { min:0.55, name:"ОК",       col:"#ffe27a" },
  { min:0.00, name:"МИМО",     col:"#ff7a45" }
];

// Фичи сравнения: углы {a,b,c} через ang3()/ang3w() (метры, world-фрейм),
// tilt — наклон корпуса, spread — развод рук, twist — кручение (только world).
export const FEATURES = [
  { key:"lElbow", name:"локоть L", a:I.LSH,  b:I.LEL, c:I.LWR },
  { key:"rElbow", name:"локоть R", a:I.RSH,  b:I.REL, c:I.RWR },
  { key:"lKnee",  name:"колено L", a:I.LHIP, b:I.LKN, c:I.LAN },
  { key:"rKnee",  name:"колено R", a:I.RHIP, b:I.RKN, c:I.RAN },
  { key:"lHip",   name:"бедро L",  a:I.LSH,  b:I.LHIP, c:I.LKN },
  { key:"rHip",   name:"бедро R",  a:I.RSH,  b:I.RHIP, c:I.RKN },
  { key:"tilt",   name:"наклон",   tilt:true },
  { key:"spread", name:"развод рук", spread:true },
  { key:"twist",  name:"кручение", twist:true }
];

// Пресеты упражнений: первичная фича, амплитуда цикла, окно, допуск и подсказка.
export const EXERCISES = {
  auto:  { name:"— авто —", primary:"top", amp:25, win:null, thr:null,
           tip:"авто-детект: цикл / поток / удержание по эталону A" },
  squat: { name:"присед", primary:"knee", amp:35, win:1, thr:15,
           tip:"следите за коленями; амплитуда цикла ~35°" },
  push:  { name:"отжимания", primary:"elbow", amp:45, win:1, thr:10,
           tip:"следите за локтями; корпус прямой" },
  lunge: { name:"выпады", primary:"hip", amp:30, win:1, thr:12,
           tip:"колено/бедро; шаг вперёд" },
  yogaFlow:{ name:"йога-поток", primary:"top", amp:15, win:1, thr:12,
           tip:"поток поз: считаются фазы, окно 1с — строже к ритму" },
  yogaHold:{ name:"йога-поза", primary:"top", amp:10, win:0.5, thr:8,
           tip:"удержание: длительность + точность угла, окно 0.5с" },
  plank: { name:"планка", primary:"tilt", amp:6, win:0.5, thr:5,
           tip:"корпус прямой, не проседать; удержание" }
};

// Хоткеи-циклы: значения селекторов, переключаемые клавишами B/S/P.
export const CYCLES = {
  bg: ["video","dim","black","ghost"],
  style: ["stick","full","neon","ghost"],
  poses: ["1","2","3","4"]
};
export const PART_KEYS = { h:"pHead", t:"pTorso", a:"pArms", l:"pLegs" };

// Сообщения об ошибках видео по кодам MediaError.
export const MEDIA_ERR = {
  1: "загрузка прервана",
  2: "ошибка чтения файла",
  3: "DECODE — контейнер открылся, но поток не декодируется (10-битный профиль, HDR, битый файл)",
  4: "SRC_NOT_SUPPORTED — браузер не берётся за этот кодек/контейнер"
};