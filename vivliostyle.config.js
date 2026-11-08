import { VFM } from "@vivliostyle/vfm";

const isPrint = process.argv.includes("print.pdf");

const def = {
  //デフォルト２分でタイムアウトしちゃうので、ローカルコンパイル対応のため追加
  timeout: 300000,   // 5 分

  title: "技術加速研究所 LLM調査報告書 Vol1", // populated into `publication.json`, default to `title` of the first entry or `name` in `package.json`.
  author: "GreenRyder <technology-acceleration-lab@greenryder.net>", // default to `author` in `package.json` or undefined.
  language: "ja", // default to undefined.
  size: "JIS-A5", // JIS-B5: 教科書サイズ、A5: 最近流行りの小さいサイズの技術書
  theme: [
    "./fonts",
    "./theme-nice-techbook2",
  ],
  entry: [
    // 表紙
    // { rel: "cover" },

    // 扉
    "title.html",
    // 前書き
    "01-preface.md",

    // 目次
    { rel: "contents" },

    "./ryder472/aws-llm-security.md",
    
    "./yoshio/01.md",

    "./kushizam/01.md",

    "./hayao/01.md",

  // 後書き
    "90-postscript.md",
    "98-authors.md",
    "99-colophon.md",
  ],
  entryContext: "./src",

  // output: [ // path to generate draft file(s). default to '{title}.pdf'
  //   './output.pdf', // the output format will be inferred from the name.
  //   {
  //     path: './book',
  //     format: 'webpub',
  //   },
  // ],
  workspaceDir: ".vivliostyle", // directory which is saved intermediate files.
  toc: {
    title: "目次", // title of table of contents. default to 'Contents'.
    sectionDepth: 2,
    includeCover: false, // include cover page in table of contents. default to 'false'.
  },
  // cover: './cover.png', // cover image. default to undefined.
  vfm: {
    // options of VFM processor
    //   hardLineBreaks: true, // converts line breaks of VFM to <br> tags. default to 'false'.
    //   disableFormatHtml: true, // disables HTML formatting. default to 'false'.
  },
};

if (isPrint) {
  def.theme = [
    ...def.theme,
    // グレースケール印刷可能なPDF
    "./theme-nice-techbook2/theme-print-pdf.css",
  ];
} else {
  def.theme = [
    ...def.theme,
    // オンライン向けのフルカラーPDF
    "./theme-nice-techbook2/theme-online-pdf.css",
    "./theme-nice-techbook2/theme-base/css/lib/prism/base.css",
    "./theme-nice-techbook2/theme-base/css/lib/prism/theme-okaidia.css",
  ];
}

export default def;
