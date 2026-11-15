# Rounds frontend

React + Vite + TypeScript + Tailwind.

```bash
npm install
npm run dev      # http://localhost:5173, needs the backend on :8000 (see ../README.md)
npm run build    # type-check + production build
npm run lint
```

- `src/types.ts`: mirrors `backend/app/models/` (shared contract). Change both together.
- `src/api.ts`: `/api` client and the `/agent` SSE client.
- `src/useAgent.ts`: one agent thread, which streams events into chat, todos and the approval card.
- `src/components/`:
  - `FloorPlan` (SVG, routes along A* paths)
  - `PlanPanel`
  - `ApprovalCard`
  - `DispatchPanel`
  - `AgentChat`
- **3D tour:** a plain Matterport embed iframe, so no SDK key is needed in the browser.
