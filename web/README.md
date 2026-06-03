# web

> React 智控台 — 设备管理、对话历史、IoT 控制、实时日志

## 技术栈

- **React 18** + **TypeScript**
- **Vite** 构建
- **Tailwind CSS** 样式
- **shadcn/ui 风格** 组件（手写精简版）
- **Zustand** 状态管理
- **TanStack Query** 服务端状态
- **React Router** 路由
- **Lucide Icons** 图标

## 快速开始

```bash
# 安装依赖
pnpm install    # 推荐
# 或 npm install / yarn

# 启动开发服务器
pnpm dev

# 构建生产版本
pnpm build
```

开发服务器默认在 http://localhost:3000，Vite 会代理：
- `/api/*` → `http://127.0.0.1:8000`（桥接服务 HTTP API，V2）
- `/xiaozhi/*` → `ws://127.0.0.1:8000`（桥接 WebSocket）

## 目录结构

```
src/
├── App.tsx             # 根组件
├── main.tsx            # 入口
├── index.css           # 全局样式（含 CSS 变量主题）
├── components/
│   ├── Sidebar.tsx     # 左侧导航
│   ├── Topbar.tsx      # 顶部栏
│   └── ui/             # 基础 UI 组件
│       ├── button.tsx
│       ├── card.tsx
│       ├── input.tsx
│       └── label.tsx
├── pages/
│   ├── Dashboard.tsx
│   ├── Devices.tsx
│   ├── Conversations.tsx
│   ├── Iot.tsx
│   ├── Settings.tsx
│   └── Logs.tsx
└── lib/
    ├── api.ts          # 后端 API 封装
    ├── store.ts        # Zustand 状态
    └── utils.ts        # 工具函数
```

## 主题

- 默认深色（参考 Linear / Vercel 设计语言）
- 支持浅色切换（顶栏右侧按钮）
- 主题变量定义在 `src/index.css`，可定制

## 路线图

- **V1**：基础 UI + 静态数据 ✅ 当前
- **V2**：接入真实 API + WebSocket 实时数据
- **V3**：添加设备详情、对话详情、IoT 控制面板
- **V4**：添加图表分析、用户系统
