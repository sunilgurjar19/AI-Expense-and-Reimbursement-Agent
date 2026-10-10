import { MoneyPipe, formatMoney } from './money.pipe';

describe('formatMoney', () => {
  it('formats rupees with Indian digit grouping by default', () => {
    expect(formatMoney(1234.5)).toBe('₹1,234.50');
    expect(formatMoney(123456.789)).toBe('₹1,23,456.79');
  });

  it('always shows two decimals in standard notation', () => {
    expect(formatMoney(0)).toBe('₹0.00');
    expect(formatMoney(99)).toBe('₹99.00');
  });

  it('formats negative amounts', () => {
    expect(formatMoney(-250)).toBe('-₹250.00');
  });

  it('formats other currencies', () => {
    expect(formatMoney(1234.5, 'USD')).toBe('$1,234.50');
    expect(formatMoney(99, 'EUR')).toBe('€99.00');
  });

  it('uses Indian compact units (thousand / lakh / crore) when compact', () => {
    expect(formatMoney(950, 'INR', true)).toBe('₹950');
    expect(formatMoney(1500, 'INR', true)).toBe('₹1.5K');
    expect(formatMoney(123456, 'INR', true)).toBe('₹1.2L');
    expect(formatMoney(25_000_000, 'INR', true)).toBe('₹2.5Cr');
  });

  it.each([null, undefined, Number.NaN])('renders a dash for a missing value (%s)', (value) => {
    expect(formatMoney(value)).toBe('—');
  });

  it('falls back to "<code> <amount>" when Intl rejects the currency code', () => {
    expect(formatMoney(12.5, 'RUPEES')).toBe('RUPEES 12.50');
  });

  it('builds one formatter per currency/notation pair and reuses it', () => {
    const ctor = vi.spyOn(Intl, 'NumberFormat');

    formatMoney(1, 'SEK', true);
    formatMoney(2, 'SEK', true);
    formatMoney(3, 'SEK', true);

    expect(ctor).toHaveBeenCalledTimes(1);
  });
});

describe('MoneyPipe', () => {
  const pipe = new MoneyPipe();

  it('delegates to formatMoney with INR as the default currency', () => {
    expect(pipe.transform(1234.5)).toBe('₹1,234.50');
  });

  it('passes currency and compact flag through', () => {
    expect(pipe.transform(1234.5, 'USD')).toBe('$1,234.50');
    expect(pipe.transform(123456, 'INR', true)).toBe('₹1.2L');
  });

  it('renders a dash for null', () => {
    expect(pipe.transform(null)).toBe('—');
  });
});
