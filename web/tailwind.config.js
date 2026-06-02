/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Design tokens — single source of truth for all components
        surface: {
          base:  '#0a0a1a',   // page background
          panel: '#050509',   // panel / header backgrounds
          card:  '#0d0d1a',   // card / bubble backgrounds
          input: '#1e1e2e',   // input fields
          hover: '#0f172a',   // hover state
          active:'#1e293b',   // selected / active state
          code:  '#0d0d1a',   // code blocks
        },
        border: {
          dim:    '#1a1a2e',  // subtle dividers
          base:   '#1e293b',  // regular borders
          strong: '#334155',  // visible borders
        },
        text: {
          primary:   '#e2e8f0',
          secondary: '#94a3b8',
          muted:     '#64748b',
          faint:     '#475569',
          ghost:     '#334155',
        },
        accent: {
          blue:   '#2563eb',
          'blue-light': '#60a5fa',
          green:  '#22c55e',
          orange: '#f97316',
          purple: '#a855f7',
          yellow: '#eab308',
          red:    '#dc2626',
          pink:   '#ec4899',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      animation: {
        'dot-bounce': 'dotBounce 1.2s ease-in-out infinite',
        shimmer:      'shimmer 1.5s ease-in-out infinite',
        'fade-in':    'fadeIn 0.2s ease-out',
        'slide-up':   'slideUp 0.25s ease-out',
        'slide-down': 'slideDown 0.25s ease-out',
        'event-slide': 'eventSlide 0.25s ease-out',
      },
      keyframes: {
        dotBounce: {
          '0%,80%,100%': { transform: 'scale(0.6)', opacity: '0.4' },
          '40%':          { transform: 'scale(1)',   opacity: '1'   },
        },
        shimmer: {
          '0%':   { backgroundPosition: '-200% center' },
          '100%': { backgroundPosition: '200% center'  },
        },
        fadeIn: {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to:   { opacity: '1', transform: 'translateY(0)'   },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to:   { opacity: '1', transform: 'translateY(0)'   },
        },
        slideDown: {
          from: { opacity: '0', transform: 'translateY(-8px)' },
          to:   { opacity: '1', transform: 'translateY(0)'    },
        },
        eventSlide: {
          from: { transform: 'translateX(16px)', opacity: '0' },
          to:   { transform: 'translateX(0)',    opacity: '1' },
        },
      },
    },
  },
  plugins: [],
};
