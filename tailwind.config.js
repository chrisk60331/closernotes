/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/**/*.js",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Backboard palette (light + derived darks)
        bb: {
          cloud: '#EDEFF7',
          steel: '#BCBFCC',
          blue: '#007BFC',
          blueDark: '#0066D6',
          phantom: '#1E1E24',
          cloudDark: '#141621',
          steelDark: '#2B2F3D',
          phantomLight: '#F5F6FA',
        },
      },
      fontFamily: {
        sans: ['Manrope', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
