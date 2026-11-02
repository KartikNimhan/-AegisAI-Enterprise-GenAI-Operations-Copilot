// jest-axe ships no type declarations. `@types/jest-axe` would pull in Jest's global types, which
// clash with Vitest's, so only the one function the tests use is declared here.
declare module 'jest-axe' {
  import type { AxeResults, RunOptions, Spec } from 'axe-core'

  export function configureAxe(
    options?: RunOptions & { globalOptions?: Spec; impactLevels?: string[] },
  ): (html: Element | string, options?: RunOptions) => Promise<AxeResults>
}
