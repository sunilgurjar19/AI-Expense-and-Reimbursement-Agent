import { Pipe, PipeTransform } from '@angular/core';

const formatters = new Map<string, Intl.NumberFormat>();

function formatter(currency: string, compact: boolean): Intl.NumberFormat {
  const key = `${currency}:${compact}`;
  let fmt = formatters.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency,
      notation: compact ? 'compact' : 'standard',
      maximumFractionDigits: compact ? 1 : 2,
      minimumFractionDigits: compact ? 0 : 2,
    });
    formatters.set(key, fmt);
  }
  return fmt;
}

export function formatMoney(value: number | null | undefined, currency = 'INR', compact = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  try {
    return formatter(currency, compact).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

@Pipe({ name: 'money' })
export class MoneyPipe implements PipeTransform {
  transform(value: number | null | undefined, currency = 'INR', compact = false): string {
    return formatMoney(value, currency, compact);
  }
}
