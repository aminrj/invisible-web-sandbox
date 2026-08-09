(function () {
  'use strict';

  function init() {
    try {
      var buyButton = document.querySelector('.btn-primary-buy');
      if (buyButton) {
        buyButton.addEventListener('click', function () {
          try {
            buyButton.disabled = true;
            setTimeout(function () {
              buyButton.disabled = false;
            }, 800);
          } catch (e) {
            console.error('Buy button handler error:', e);
          }
        });
      }
    } catch (e) {
      console.error('Initialization error:', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
