// What the type check assumes beyond the browser's own types.
//
// The page treats the DOM loosely, the way plain browser JavaScript does: $('#x').hidden, e.target.closest(...), e.key on
// a listener's event. TypeScript would flag every one of those (a querySelector result is an Element, not an HTMLElement),
// which is noise rather than bugs, so these widen the DOM types the page uses. Everything else is checked as written.
declare const THREE: any;
interface Element extends ElementCSSInlineStyle, HTMLOrSVGElement {
  hidden: boolean; disabled: boolean; value: any; checked: boolean; title: string; innerText: string;
  complete: boolean; offsetWidth: number; offsetHeight: number; offsetTop: number; offsetLeft: number; click(): void;
  setAttribute(qualifiedName: string, value: string | number | boolean): void;   // the browser turns the value into text
}
interface EventTarget { closest(selectors: string): any; value?: any; dataset?: DOMStringMap; }
interface Event { key: string; relatedTarget: any; clientX: number; clientY: number; touches: any; deltaY: number; }
interface ErrorConstructor { new (message?: string | number): Error; }   // new Error(r.status): the status code as the message
interface Node { contains(other: any): boolean; }   // dd.contains(e.target): an event target is a node here
