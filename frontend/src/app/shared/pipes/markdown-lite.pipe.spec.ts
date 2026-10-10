import { MarkdownLitePipe } from './markdown-lite.pipe';

describe('MarkdownLitePipe', () => {
  const pipe = new MarkdownLitePipe();

  it.each([null, undefined, ''])('returns an empty string for %j', (value) => {
    expect(pipe.transform(value)).toBe('');
  });

  it('leaves plain text untouched', () => {
    expect(pipe.transform('Your claim is ready')).toBe('Your claim is ready');
  });

  it('renders **bold** as <strong>', () => {
    expect(pipe.transform('Total is **₹827**')).toBe('Total is <strong>₹827</strong>');
  });

  it('renders *italic* as <em>', () => {
    expect(pipe.transform('This is *optional*')).toBe('This is <em>optional</em>');
  });

  it('handles bold and italic in the same message', () => {
    expect(pipe.transform('**Ready** to submit - *nice work*')).toBe(
      '<strong>Ready</strong> to submit - <em>nice work</em>',
    );
  });

  it('converts newlines to <br>', () => {
    expect(pipe.transform('line one\nline two\n\nline four')).toBe('line one<br>line two<br><br>line four');
  });

  it('does not treat a spaced asterisk (multiplication, bullets) as emphasis', () => {
    expect(pipe.transform('2 * 3 * 4')).toBe('2 * 3 * 4');
    expect(pipe.transform('* first item')).toBe('* first item');
  });

  describe('HTML safety', () => {
    it('escapes markup so agent text cannot inject elements', () => {
      expect(pipe.transform('<img src=x onerror="alert(1)">')).toBe(
        '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;',
      );
    });

    it('escapes ampersands and single quotes', () => {
      expect(pipe.transform("Tom & Jerry's")).toBe('Tom &amp; Jerry&#39;s');
    });

    it('escapes before formatting, so markup inside bold stays inert', () => {
      expect(pipe.transform('**<b>x</b> & y**')).toBe('<strong>&lt;b&gt;x&lt;/b&gt; &amp; y</strong>');
    });
  });
});
