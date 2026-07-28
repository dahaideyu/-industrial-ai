export function scrollToPdfPage(page) {
  const el = document.getElementById(`pdf-page-${page}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}
