# RADA_COFFEE — frontend (Next.js 14, App Router)

Interface « camera-first » : Live Operations (lecteur + fil d'événements + état opérationnel), Cameras, Events, Revenue Intelligence, Alerts & Review, Reports, Settings.

```bash
cp .env.example .env.local   # renseigner NEXT_PUBLIC_API_URL
npm install
npm run dev                  # http://localhost:3000
npm run typecheck && npm run lint && npm test && npm run build
```

Stack : Next.js, React, TypeScript strict, Tailwind, composants shadcn/ui (Radix) dans `src/components/ui`, Lucide, Recharts.
Les règles métier et les calculs de perte restent côté backend. Voir `../docs/frontend_streaming.md` pour le flux vidéo et les contrats manquants.
