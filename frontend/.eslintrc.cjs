module.exports = {
  root: true,
  env: {
    browser: true,
    es2020: true,
  },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react-hooks'],
  extends: ['eslint:recommended', 'plugin:@typescript-eslint/recommended', 'plugin:react-hooks/recommended'],
  ignorePatterns: ['dist', 'node_modules'],
  rules: {
    // 现有代码大量使用 any（尤其是 API 层与历史页面），暂不强制收敛。
    '@typescript-eslint/no-explicit-any': 'off',
    // 与 TS 的 noUnused* 规则对齐：允许用 `_` 前缀显式标记“有意未使用”的参数/变量。
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
    ],
    // Hooks 依赖数组在现有代码中经常有意省略，避免在未统一规范前引入大量噪音。
    'react-hooks/exhaustive-deps': 'off',

    // 现存文件包含历史缩进风格（tabs/spaces 混用），先允许通过；后续可配合 formatter 逐步收敛。
    'no-mixed-spaces-and-tabs': 'off',

    // 与现有工程实践保持一致：以下规则会在当前代码量下引入大量“非功能性噪音”。
    'no-constant-condition': 'off',
    'no-empty': 'off',
    'no-irregular-whitespace': 'off',
    'no-unsafe-finally': 'off',
    'no-useless-catch': 'off',
    'prefer-const': 'off',
  },
}
