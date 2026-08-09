(function () {
    'use strict';

    function smoothScrollTo(targetSelector) {
        if (!targetSelector) {
            return;
        }
        var target = document.querySelector(targetSelector);
        if (!target) {
            return;
        }
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function setupNavScrolling() {
        var scrollButtons = document.querySelectorAll('[data-scroll-target]');
        if (!scrollButtons || scrollButtons.length === 0) {
            return;
        }
        scrollButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var target = btn.getAttribute('data-scroll-target');
                smoothScrollTo(target);
            });
        });

        var navLinks = document.querySelectorAll('nav .nav-link[href^="#"]');
        navLinks.forEach(function (link) {
            link.addEventListener('click', function (event) {
                var href = link.getAttribute('href');
                if (!href) {
                    return;
                }
                var targetId = href.trim();
                if (targetId.length > 1) {
                    event.preventDefault();
                    smoothScrollTo(targetId);
                    closeMobileNav();
                }
            });
        });
    }

    var mobileNav;
    var menuToggle;

    function closeMobileNav() {
        if (!mobileNav || !menuToggle) {
            return;
        }
        mobileNav.classList.remove('active');
        menuToggle.setAttribute('aria-expanded', 'false');
    }

    function setupMobileNav() {
        mobileNav = document.querySelector('.nav-mobile');
        menuToggle = document.querySelector('.menu-toggle');
        if (!mobileNav || !menuToggle) {
            return;
        }
        menuToggle.addEventListener('click', function () {
            var isActive = mobileNav.classList.toggle('active');
            menuToggle.setAttribute('aria-expanded', isActive ? 'true' : 'false');
        });

        window.addEventListener('resize', function () {
            if (window.innerWidth > 720) {
                closeMobileNav();
            }
        });
    }

    function validateEmail(value) {
        if (!value) {
            return false;
        }
        var pattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return pattern.test(value);
    }

    function setupForm() {
        var form = document.getElementById('purchase-form');
        var successBanner = document.getElementById('success-banner');
        if (!form || !successBanner) {
            return;
        }

        function showError(fieldName, message) {
            var messageEl = form.querySelector('.validation-message[data-for="' + fieldName + '"]');
            if (!messageEl) {
                return;
            }
            messageEl.textContent = message;
            messageEl.classList.add('active');
            setTimeout(function () {
                messageEl.classList.remove('active');
            }, 300);
        }

        function clearError(fieldName) {
            var messageEl = form.querySelector('.validation-message[data-for="' + fieldName + '"]');
            if (!messageEl) {
                return;
            }
            messageEl.textContent = '';
            messageEl.classList.remove('active');
        }

        form.addEventListener('submit', function (event) {
            event.preventDefault();

            var nameInput = document.getElementById('name');
            var emailInput = document.getElementById('email');
            var regionInput = document.getElementById('region');

            if (!nameInput || !emailInput || !regionInput) {
                return;
            }

            var nameValue = nameInput.value.trim();
            var emailValue = emailInput.value.trim();
            var regionValue = regionInput.value.trim();

            var hasError = false;

            clearError('name');
            clearError('email');
            clearError('region');

            if (!nameValue) {
                showError('name', 'Please enter your full name.');
                hasError = true;
            }

            if (!emailValue) {
                showError('email', 'Please enter your email address.');
                hasError = true;
            } else if (!validateEmail(emailValue)) {
                showError('email', 'Please enter a valid email address.');
                hasError = true;
            }

            if (!regionValue) {
                showError('region', 'Please enter your city and country.');
                hasError = true;
            }

            if (hasError) {
                successBanner.classList.remove('visible');
                successBanner.textContent = '';
                return;
            }

            successBanner.textContent = 'Thank you. We have recorded your interest in Auralis ANC Pro. A pre-order link will be sent to your email once ordering opens in your region.';
            successBanner.classList.add('visible');

            form.reset();
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        try {
            setupNavScrolling();
            setupMobileNav();
            setupForm();
        } catch (e) {
            console.error('Initialization error:', e);
        }
    });
})();
