/**
 * Copy text to clipboard with HTTP fallback.
 * - HTTPS: uses navigator.clipboard.writeText (modern API)
 * - HTTP:  falls back to document.execCommand('copy') (legacy but universal)
 */
export async function clipboardCopy(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // clipboard API failed (e.g. permission denied), fall through to legacy
    }
  }

  // Legacy fallback for HTTP or permission issues
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}
