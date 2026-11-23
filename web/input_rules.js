/** 输入规则。空白不发送；Enter 发送；Shift+Enter 换行；组词中的 Enter 不发送。 */
export function shouldSendOnEnter(event) {
  if (!event || event.key !== "Enter") return false;
  if (event.shiftKey) return false;
  if (event.isComposing || event.keyCode === 229) return false;
  return true;
}

export function normalizeContent(value) {
  return (value || "").replace(/\u00a0/g, " ").trim();
}
