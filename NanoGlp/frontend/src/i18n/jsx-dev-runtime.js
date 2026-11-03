import * as ReactJSXDevRuntime from 'react/jsx-dev-runtime';
import { translatePropsIfNeeded, Fragment } from './jsx-runtime';

export { Fragment };

export function jsxDEV(type, props, key, isStaticChildren, source, self) {
  return ReactJSXDevRuntime.jsxDEV(
    type,
    translatePropsIfNeeded(type, props),
    key,
    isStaticChildren,
    source,
    self
  );
}
