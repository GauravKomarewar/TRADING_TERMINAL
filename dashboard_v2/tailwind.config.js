/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#22d3ee',
        accent: '#818cf8',
        profit: '#4ade80',
        loss: '#fb7185',
        warning: '#fbbf24',
        'bg-base': '#0c0e14',
        'bg-surface': '#131722',
        'bg-elevated': '#1e222d',
        'bg-hover': '#2a2e3e',
        'bg-input': '#181c27',
        border: '#2a2e3e',
        'border-subtle': '#1e222d',
        'text-bright': '#e5e7eb',
        'text-primary': '#d1d4dc',
        'text-secondary': '#848e9c',
        'text-muted': '#565c66',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      keyframes: {
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 5px rgba(34,211,238,.2)' },
          '50%': { boxShadow: '0 0 15px rgba(34,211,238,.5)' },
        },
        'flash-value': {
          '0%': { backgroundColor: 'rgba(34,211,238,.2)' },
          '100%': { backgroundColor: 'transparent' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      animation: {
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'flash-value': 'flash-value .6s ease-out',
        'slide-up': 'slide-up .25s ease-out',
        'fade-in': 'fade-in .3s ease-out',
        shimmer: 'shimmer 2s linear infinite',
      },
    },
  },
  plugins: [],
}
