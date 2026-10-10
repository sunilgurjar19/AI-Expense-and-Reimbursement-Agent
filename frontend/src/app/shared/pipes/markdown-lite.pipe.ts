import { Pipe, PipeTransform } from '@angular/core';

const ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/** Safe subset of markdown for agent messages: **bold**, *italic*, line breaks. */
@Pipe({ name: 'markdownLite' })
export class MarkdownLitePipe implements PipeTransform {
  transform(text: string | null | undefined): string {
    if (!text) return '';
    return text
      .replace(/[&<>"']/g, (c) => ESCAPES[c])
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*(?!\s)(.+?)\*/g, '$1<em>$2</em>')
      .replace(/\n/g, '<br>');
  }
}
