/**
 * While a reply is still streaming, an unfinished `**bold` or `code` would show raw markers.
 * Close open markers (and hide a lone trailing `*`) so the preview always renders cleanly.
 */
export function balanceMarkdown(text: string): string {
  let out = text;
  if (/(^|[^*])\*$/.test(out)) out = out.slice(0, -1); // maybe the first half of "**"
  if ((out.match(/```/g) ?? []).length % 2 === 1) return out + "\n```";
  if ((out.match(/`/g) ?? []).length % 2 === 1) out += "`";
  const withoutCode = out.replace(/`[^`]*`/g, "");
  if ((withoutCode.match(/\*\*/g) ?? []).length % 2 === 1) {
    out = out.endsWith("**") ? out.slice(0, -2) : out + "**";
  }
  return out;
}
