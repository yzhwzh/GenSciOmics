import '@testing-library/jest-dom'

globalThis.ResizeObserver = class ResizeObserver {
  observe() {}; unobserve() {}; disconnect() {}
}

Element.prototype.scrollIntoView = () => {}
