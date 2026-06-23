export type ToastType = 'success' | 'error' | 'info';

export interface ToastItem {
  id: string;
  message: string;
  type: ToastType;
}

type Setter = (fn: (prev: ToastItem[]) => ToastItem[]) => void;
let _setter: Setter | null = null;

export function registerToastSetter(fn: Setter | null) {
  _setter = fn;
}

export function showToast(message: string, type: ToastType = 'info', duration = 3500) {
  if (!_setter) return;
  const id = Math.random().toString(36).slice(2, 9);
  _setter(prev => [...prev, { id, message, type }]);
  setTimeout(() => {
    _setter!(prev => prev.filter(t => t.id !== id));
  }, duration);
}
