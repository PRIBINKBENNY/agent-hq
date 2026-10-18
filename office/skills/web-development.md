# Websites in 2026 (updated 2026-10-18)
- Default stack: Next.js (App Router) + TypeScript + Tailwind CSS v4 (+ shadcn/ui components), deployed free on Vercel;
  or plain static HTML/CSS/JS (or Astro) for simple sites on GitHub Pages / Cloudflare Pages.
- React Server Components by default; mark only interactive parts as client components (over-using client components
  bloats the JavaScript bundle).
- Tailwind v4 changed setup: check a tutorial's version before copying config. Put repeated utility groups into
  components and design tokens into the theme.
- Accessibility target: WCAG 2.2 AA (semantic HTML, labels, keyboard focus, contrast, alt text, reduced motion).
- Performance: Core Web Vitals (LCP, INP, CLS); optimise images, fonts and third-party scripts; measure with Lighthouse.
- SEO: real titles/descriptions, Open Graph tags, sitemap, fast first load.
Sources: sitepoint.com (Tailwind in React/Next.js), bixtech.ai (React/Next/Tailwind 2026 guide), serviots.com (Next.js
best practices 2026), W3C WCAG 2.2 (Recommendation since 2023), web.dev Core Web Vitals (INP replaced FID in 2024).
