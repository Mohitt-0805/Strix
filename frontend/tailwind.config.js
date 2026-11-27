/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        canvas: '#F8FAFC',
        surface: '#FFFFFF',
        hairline: '#E2E8F0',
        sidebar: '#0F172A',
        sidebarActive: '#1E293B',
        steel: {
          DEFAULT: '#1D4ED8',
          light: '#2563EB',
          hover: '#1E40AF',
          tint: '#EFF6FF',
          border: '#BFDBFE',
        },
        status: {
          emerald: '#047857',
          emeraldBg: '#ECFDF5',
          emeraldBorder: '#A7F3D0',
          amber: '#B45309',
          amberBg: '#FFFBEB',
          amberBorder: '#FDE68A',
          crimson: '#B91C1C',
          crimsonBg: '#FEF2F2',
          crimsonBorder: '#FECACA',
          slateText: '#475569',
          slateBg: '#F1F5F9',
          slateBorder: '#CBD5E1',
        },
      },
    },
  },
  plugins: [],
}
