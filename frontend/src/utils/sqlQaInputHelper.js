export function fillQuestionInput(text) {
  const textarea = document.querySelector('[data-sqlqa-input]')
  if (!textarea) return
  const nativeSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
  if (nativeSetter) {
    nativeSetter.call(textarea, text)
  } else {
    textarea.value = text
  }
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
  textarea.focus()
}
