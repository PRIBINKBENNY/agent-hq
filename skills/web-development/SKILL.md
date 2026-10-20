---
name: web-development
description: "Use when the task needs Websites in 2026. Current practice as of 2026-10-18, with sources."
metadata:
  updated: 2026-10-18
  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/web-development.md
---

# Websites in 2026

- Default stack: Next.js (App Router) + TypeScript + Tailwind CSS v4 (+ shadcn/ui components), deployed free on Vercel;
  or plain static HTML/CSS/JS (or Astro) for simple sites on GitHub Pages / Cloudflare Pages.
- React Server Components by default; mark only interactive parts as client components (over-using client components
  bloats the JavaScript bundle).
- Tailwind v4 changed setup: check a tutorial's version before copying config. Put repeated utility groups into
  components and design tokens into the theme.
- Accessibility target: WCAG 2.2 AA (semantic HTML, labels, keyboard focus, contrast, alt text, reduced motion).
- Performance: Core Web Vitals (LCP, INP, CLS); optimise images, fonts and third-party scripts; measure with Lighthouse.
- SEO: real titles/descriptions, Open Graph tags, sitemap, fast first load.

best practices 2026), W3C WCAG 2.2 (Recommendation since 2023), web.dev Core Web Vitals (INP replaced FID in 2024).

## Sources

sitepoint.com (Tailwind in React/Next.js), bixtech.ai (React/Next/Tailwind 2026 guide), serviots.com (Next.js
