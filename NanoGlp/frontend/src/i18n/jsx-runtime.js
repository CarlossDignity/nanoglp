import * as ReactJSXRuntime from 'react/jsx-runtime';
import { getActiveLang, translateText } from './translations';

const SKIP_TAGS = new Set(['script', 'style', 'code', 'pre', 'svg', 'path']);

function translateChildren(children) {
  if (typeof children === 'string') {
    return translateText(children, 'en');
  }
  if (Array.isArray(children)) {
    const allPrimitive = children.every(
      (c) => typeof c === 'string' || typeof c === 'number' || c === null || c === undefined || typeof c === 'boolean'
    );
    if (allPrimitive && children.some((c) => typeof c === 'string' && c.trim().length > 0)) {
      const joined = children
        .filter((c) => c !== null && c !== undefined && typeof c !== 'boolean')
        .join('');
      return translateText(joined, 'en');
    }
    return children.map((child) => (typeof child === 'string' ? translateText(child, 'en') : child));
  }
  return children;
}

export function translatePropsIfNeeded(type, props) {
  if (!props || getActiveLang() !== 'en') return props;
  if (props['data-no-i18n'] === 'true') return props;
  if (typeof type === 'string' && SKIP_TAGS.has(type)) return props;

  let nextProps = null;
  const ensureCopy = () => {
    if (!nextProps) nextProps = { ...props };
    return nextProps;
  };

  if (typeof type === 'string' && props.children !== undefined) {
    const translatedChildren = translateChildren(props.children);
    if (translatedChildren !== props.children) {
      ensureCopy().children = translatedChildren;
    }
  }

  for (const attr of ['placeholder', 'title', 'aria-label', 'label', 'subtitle']) {
    if (typeof props[attr] === 'string' && props[attr].trim().length > 0) {
      const translatedAttr = translateText(props[attr], 'en');
      if (translatedAttr !== props[attr]) {
        ensureCopy()[attr] = translatedAttr;
      }
    }
  }

  return nextProps || props;
}

export const Fragment = ReactJSXRuntime.Fragment;

export function jsx(type, props, key) {
  return ReactJSXRuntime.jsx(type, translatePropsIfNeeded(type, props), key);
}

export function jsxs(type, props, key) {
  return ReactJSXRuntime.jsxs(type, translatePropsIfNeeded(type, props), key);
}
