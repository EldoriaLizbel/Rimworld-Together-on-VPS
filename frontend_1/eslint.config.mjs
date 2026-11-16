export default [{
  files: ["**/*.{js,jsx,mjs}"],
  ignores: [".next/**", "node_modules/**"],
  languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
  rules: {
    "no-dupe-keys": "error", "no-dupe-args": "error", "no-unreachable": "error",
    "no-constant-condition": ["error", { checkLoops: false }], "no-fallthrough": "error",
    "no-invalid-regexp": "error", "no-unsafe-finally": "error", "no-unsafe-optional-chaining": "error",
  },
}];
