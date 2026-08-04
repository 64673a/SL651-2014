/**
 * 复制文本到剪贴板。
 * HTTP 非本机不是 secure context，navigator.clipboard 不可用。
 * 弹窗内还有 focus trap，临时 textarea 常被抢焦点导致「成功但剪贴板为空」，
 * 因此回退路径用 copy 事件直接写入 clipboardData。
 */
export async function writeClipboard(text) {
  const value = String(text ?? "");

  if (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    navigator.clipboard?.writeText
  ) {
    await navigator.clipboard.writeText(value);
    return;
  }

  let written = false;
  const onCopy = (e) => {
    e.clipboardData?.setData("text/plain", value);
    e.preventDefault();
    written = true;
  };

  document.addEventListener("copy", onCopy);
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } finally {
    document.removeEventListener("copy", onCopy);
  }

  if (ok && written) return;

  // 兜底：挂到当前对话框内，避免 Reka/Nuxt UI focus trap 抢走焦点
  const active = document.activeElement;
  const root =
    (active && typeof active.closest === "function"
      ? active.closest('[role="dialog"]') ||
        active.closest("[data-reka-dialog-content]")
      : null) || document.body;

  const ta = document.createElement("textarea");
  ta.value = value;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
  root.appendChild(ta);
  ta.focus();
  ta.select();
  ta.setSelectionRange(0, ta.value.length);
  try {
    ok = document.execCommand("copy");
  } finally {
    root.removeChild(ta);
  }
  if (!ok) throw new Error("execCommand copy failed");
}
