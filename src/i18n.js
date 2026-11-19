/**
 * 轻量多语言模块（无依赖，经典脚本，挂到 window.I18N）。
 *
 * 设计原则：
 * - 中文内置在 locales/zh-CN.js 里，永远不读文件：任何语言包丢失、被移走、
 *   解析失败，界面最多回落到中文，不会空白、不会崩；
 * - 其它语言是 locales/<locale>.json，只在这些文件存在时才会被用到；
 * - HTML 里用 data-i18n="key" 标出文案，标签内保留中文原文作为兜底；
 * - JSON 缺 key 时回落中文，中文也缺就保留标签里写的内容，不会出现空白。
 */
(function () {
  const SUPPORTED = [
    { code: "zh-CN", label: "简体中文" },
    { code: "en-US", label: "English" },
    { code: "ja-JP", label: "日本語" },
    { code: "ko-KR", label: "한국어" },
    { code: "es-ES", label: "Español" },
  ];
  const STORAGE_KEY = "locale";
  const DEFAULT_LOCALE = "zh-CN";
  const SYSTEM = "system"; // 下拉框里「跟随系统」的值

  // 内置中文：locales/zh-CN.js 在 i18n.js 之前加载，没有它也能跑（只是中文兜底为空）
  const BUILTIN = (window.LOCALE_BUILTIN && window.LOCALE_BUILTIN[DEFAULT_LOCALE]) || null;

  let current = DEFAULT_LOCALE;
  let fallback = BUILTIN || {}; // 中文兜底
  let dict = {};

  /** 用户的选择：具体语言码、"system"，或 null（从没选过） */
  function readStored() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === SYSTEM) return SYSTEM;
      if (saved && SUPPORTED.some((item) => item.code === saved)) return saved;
    } catch (_) {}
    return null;
  }

  /** 按系统语言挑一个受支持的语言；系统语言不在列表里就回落中文 */
  function detectFromSystem() {
    const nav = (navigator.language || "").toLowerCase();
    const hit = SUPPORTED.find((item) => nav.startsWith(item.code.slice(0, 2)));
    return hit ? hit.code : DEFAULT_LOCALE;
  }

  /** 实际生效的语言码 */
  function resolve() {
    const stored = readStored();
    if (stored && stored !== SYSTEM) return stored;
    return detectFromSystem();
  }

  /** 下拉框该选中的值：没选过时就是 system */
  function choice() {
    return readStored() || SYSTEM;
  }

  async function load(code) {
    if (!code) return {};
    const res = await fetch(`locales/${code}.json`, { cache: "no-cache" });
    if (!res.ok) throw new Error(`缺少语言包：${code}`);
    return res.json();
  }

  /** 取嵌套 key：t("transcribe.model") */
  function lookup(source, key) {
    return key.split(".").reduce((acc, part) => (acc == null ? acc : acc[part]), source);
  }

  /** 翻译；vars 用于 {name} 这类占位替换 */
  function t(key, vars) {
    let text = lookup(dict, key);
    if (text == null) text = lookup(fallback, key);
    if (text == null) return key;
    if (vars && typeof text === "string") {
      text = text.replace(/\{(\w+)\}/g, (whole, name) =>
        vars[name] == null ? whole : String(vars[name])
      );
    }
    return text;
  }

  /** data-i18n-vars='{"version":"0.1.0"}' 解析成对象，格式不对就当没有变量 */
  function readVars(node) {
    const raw = node.dataset.i18nVars;
    if (!raw) return undefined;
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : undefined;
    } catch (error) {
      console.warn("[i18n] data-i18n-vars 不是合法 JSON：", raw);
      return undefined;
    }
  }

  /** 把 current 语言写进 DOM：data-i18n / data-i18n-title / data-i18n-ph / data-i18n-html */
  function apply(root) {
    const scope = root || document;

    scope.querySelectorAll("[data-i18n]").forEach((node) => {
      const text = t(node.dataset.i18n, readVars(node));
      if (text !== node.dataset.i18n) node.textContent = text;
    });

    scope.querySelectorAll("[data-i18n-html]").forEach((node) => {
      const text = t(node.dataset.i18nHtml);
      if (text !== node.dataset.i18nHtml) node.innerHTML = text;
    });

    scope.querySelectorAll("[data-i18n-title]").forEach((node) => {
      node.title = t(node.dataset.i18nTitle);
    });

    scope.querySelectorAll("[data-i18n-ph]").forEach((node) => {
      node.placeholder = t(node.dataset.i18nPh);
    });

    document.documentElement.lang = current;
    document.dispatchEvent(new CustomEvent("localechange", { detail: { locale: current } }));
  }

  /** 加载语言包并刷新 DOM，不碰存储（启动时用，避免把「跟随系统」钉死成具体语言） */
  async function loadDict(code) {
    current = code;
    if (code === DEFAULT_LOCALE) {
      // 中文不读文件，内置那份就是权威
      dict = BUILTIN || {};
      apply();
      return current;
    }
    try {
      dict = await load(code);
    } catch (error) {
      // 语言包缺失/读不出来：退回中文，界面照常可用
      console.warn("[i18n] 语言包加载失败，回落到中文：", error);
      dict = BUILTIN || {};
      current = DEFAULT_LOCALE;
    }
    apply();
    return current;
  }

  /** 切换语言：code 可以是具体语言码，也可以是 SYSTEM；会被记住 */
  async function setLocale(code) {
    const isSystem = code === SYSTEM;
    if (!isSystem && !SUPPORTED.some((item) => item.code === code)) return current;
    // 先写存储再刷新 DOM：apply() 会派发 localechange，下拉框按存储回显，
    // 顺序反过来就会在刷新时读到旧值，瞬间跳回上一个语言
    try {
      localStorage.setItem(STORAGE_KEY, isSystem ? SYSTEM : code);
    } catch (_) {}
    const applied = await loadDict(isSystem ? detectFromSystem() : code);
    if (!isSystem && applied !== code) {
      // 语言包缺失而回落中文时，存储跟着改成实际生效的语言
      try {
        localStorage.setItem(STORAGE_KEY, applied);
      } catch (_) {}
    }
    return applied;
  }

  /** 启动时调用一次 */
  async function init() {
    if (!BUILTIN) {
      // 内置中文没加载到时兜底再试一次文件（正常情况下不会走到这里）
      try {
        fallback = await load(DEFAULT_LOCALE);
      } catch (error) {
        console.warn("[i18n] 中文语言包缺失，界面保持 HTML 里的原文：", error);
        fallback = {};
      }
    }
    const target = resolve();
    await loadDict(target);
    // 跟随系统时，系统语言变了要跟着变（不写存储）
    window.addEventListener("languagechange", () => {
      if (choice() !== SYSTEM) return;
      const next = detectFromSystem();
      if (next !== current) loadDict(next);
    });
    return current;
  }

  window.I18N = {
    init,
    setLocale,
    apply,
    t,
    locale: () => current,
    choice,
    supported: SUPPORTED,
    SYSTEM,
  };
})();
