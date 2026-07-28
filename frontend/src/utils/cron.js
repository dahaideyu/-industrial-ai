// cron 表达式（分 时 日 月 周）与「每小时/每天/每周/每月/自定义」选择器状态的互转工具

export const WEEKDAY_LABELS = [
  { value: 1, label: '一' },
  { value: 2, label: '二' },
  { value: 3, label: '三' },
  { value: 4, label: '四' },
  { value: 5, label: '五' },
  { value: 6, label: '六' },
  { value: 0, label: '日' },
]

export function pad2(n) {
  return String(n).padStart(2, '0')
}

const isNum = (s) => /^\d+$/.test(s)
const isNumList = (s) => /^\d+(,\d+)*$/.test(s)

// 把 cron 字符串解析为选择器状态；无法识别的表达式落入 custom 模式，原样保留
export function parseCron(cronStr) {
  const raw = (cronStr || '').trim()
  const fallback = { mode: raw ? 'custom' : 'daily', hour: 2, minute: 0, weekdays: [1], days: [1], raw }
  const parts = raw.split(/\s+/)
  if (parts.length !== 5) return fallback

  const [m, h, dom, mon, dow] = parts
  if (mon !== '*') return fallback

  if (h === '*' && dom === '*' && dow === '*' && isNum(m)) {
    return { mode: 'hourly', hour: 2, minute: Number(m), weekdays: [1], days: [1], raw }
  }
  if (isNum(h) && isNum(m) && dom === '*' && dow === '*') {
    return { mode: 'daily', hour: Number(h), minute: Number(m), weekdays: [1], days: [1], raw }
  }
  if (isNum(h) && isNum(m) && dom === '*' && dow !== '*' && isNumList(dow)) {
    return { mode: 'weekly', hour: Number(h), minute: Number(m), weekdays: dow.split(',').map(Number), days: [1], raw }
  }
  if (isNum(h) && isNum(m) && dow === '*' && dom !== '*' && isNumList(dom)) {
    return { mode: 'monthly', hour: Number(h), minute: Number(m), weekdays: [1], days: dom.split(',').map(Number), raw }
  }
  return fallback
}

// 把选择器状态拼成 cron 字符串
export function buildCron(state) {
  const { mode, hour, minute, weekdays, days, raw } = state
  if (mode === 'hourly') return `${minute} * * * *`
  if (mode === 'daily') return `${minute} ${hour} * * *`
  if (mode === 'weekly') {
    const ds = [...new Set(weekdays)].sort((a, b) => a - b)
    return `${minute} ${hour} * * ${ds.join(',')}`
  }
  if (mode === 'monthly') {
    const ds = [...new Set(days)].sort((a, b) => a - b)
    return `${minute} ${hour} ${ds.join(',')} * *`
  }
  return (raw || '').trim()
}

// 人类可读的中文描述，用于表格展示
export function describeCron(cronStr) {
  if (!cronStr || !cronStr.trim()) return '未设置'
  const s = parseCron(cronStr)
  if (s.mode === 'hourly') return `每小时第 ${pad2(s.minute)} 分`
  if (s.mode === 'daily') return `每天 ${pad2(s.hour)}:${pad2(s.minute)}`
  if (s.mode === 'weekly') {
    const names = [...s.weekdays].sort((a, b) => a - b)
      .map((v) => WEEKDAY_LABELS.find((w) => w.value === v)?.label ?? v).join('、')
    return `每周${names} ${pad2(s.hour)}:${pad2(s.minute)}`
  }
  if (s.mode === 'monthly') {
    const names = [...s.days].sort((a, b) => a - b).join('、')
    return `每月${names}号 ${pad2(s.hour)}:${pad2(s.minute)}`
  }
  return cronStr.trim()
}
