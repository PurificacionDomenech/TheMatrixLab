// API Configuration for PWA
(function() {
  const isLocal = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  const isReplit = location.hostname.includes('replit.dev') || location.hostname.includes('replit.co');
  
  // Use location.origin as base for PWA - works when opened from published URL
  // Empty string for local/replit (uses relative URLs)
  window.API_BASE = (isLocal || isReplit) ? '' : location.origin;
  
  // Wrap fetch to use absolute URLs for API calls when running as installed PWA
  const originalFetch = window.fetch;
  window.fetch = function(url, options) {
    if (typeof url === 'string' && url.startsWith('/') && window.API_BASE) {
      url = window.API_BASE + url;
    }
    return originalFetch.apply(this, [url, options]);
  };
})();
