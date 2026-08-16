// state.js — общее состояние режима «Сравнение».
// Вынесено в отдельный модуль, чтобы features/score/compare могли читать
// и менять одни и те же данные без циклических импортов.
//  s  — «пульт» из переприсваиваемых переменных (детекторы, камера, каналы),
//  cmp — большой объект-сессия сравнения (мутируется свойствами).

export const s = {
  lmA: null,             // детектор эталона A
  lmB: null,             // детектор повтора B
  hasA: false,           // загружено видео A
  hasB: false,           // загружено видео B
  useCamB: false,        // источник B — камера
  camOn: false,          // камера включена
  camStream: null,       // MediaStream камеры
  aAnalyze: null,        // запущенный фоновый анализ эталона (для отмены)
  aAnalyzeT: null,       // таймер отложенного анализа
  chartCV: {},           // канвасы графиков по фичам
  lagTouched: false,     // пользователь вручную двигал «задержку»
  actx: null,            // AudioContext (лениво создаётся в beep)
  sound: { vol: 0.5, muted: false }  // настройки звука видео: громкость 0..1, mute=false — звук есть
};

export const cmp = {
  running:false, preview:false, markA:0, markB:0,
  samples:[], featSum:{},
  frames:0, t0:0, everyN:0, camTS:0,
  lastTimeA:-1, lastTimeB:-1, smoothA:[], smoothB:[], smoothA3D:[], smoothB3D:[],
  tsA:-1, tsB:-1, failsA:0, failsB:0, fbA:false, fbB:false, aWin:{},
  warmUntil:0, shiftSum:0, shiftCnt:0, bHist:{}, bHistS:{}, curLagA:null, lagAcq:true, lagRing:[], _dispOv:null,
  score:null, combo:0, maxCombo:0, tier:null, tierCol:null,
  detB:{}, repScores:[], exType:null, primary:null, amp:25,
  dtw:null, tag:"",
  aProf:null, maskApplied:false, gate:{}, gateSum:{}, gateN:{},
  sigmaNoise:{}, sigmaFrozen:{}, resid:{}
};