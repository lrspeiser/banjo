// Root production routes and the co-hosted test application's routes.
export function sitePath(base, path) {
  if (!['', '/test'].includes(base) || !path.startsWith('/') || path.startsWith('//'))
    throw new Error('Invalid application path');
  return base + path;
}
