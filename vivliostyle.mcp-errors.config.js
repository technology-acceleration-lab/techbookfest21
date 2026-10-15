import book from "./vivliostyle.config.js";

// The manuscript is shared with the full book; only the build scope differs.
export default {
  ...book,
  title: "MCP Toolのエラー設計",
  author: "技術加速研究所",
  entry: ["02-mcp-tool-errors.md"],
  theme: [
    "./fonts",
    "./theme-nice-techbook2",
    "./theme-nice-techbook2/theme-print-pdf.css",
    "./src/mcp-errors.css",
  ],
  toc: false,
  workspaceDir: ".vivliostyle-mcp-errors",
};
