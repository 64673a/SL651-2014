/**
 * 复制文本到剪贴板。
 * HTTP 非本机不是 secure context，navigator.clipboard 不可用，需回退到 execCommand。
 */
export async function writeClipboard(text) {
  const value = text ?? "";
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = value;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  ta.setSelectionRange(0, ta.value.length);
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } finally {
    document.body.removeChild(ta);
  }
  if (!ok) throw new Error("execCommand copy failed");
}
