/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js}"
  ],
  theme: {
    extend: {
      colors: {
        'surface': '#f5f6f8',
        'surface-container-lowest': '#ffffff',
        'surface-container-low': '#fff7df',
        'surface-container': '#fde68a',
        'on-surface': '#0f172a',
        'primary': '#b45309',
        'primary-container': '#fbbf24',
        'on-primary-container': '#1f2937',
        'secondary': '#64748b',
        'error': '#ba1a1a',
        'error-container': '#ffdad6',
      },
      fontFamily: {
        'headline': ['Space Grotesk', 'sans-serif'],
        'body': ['Manrope', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
