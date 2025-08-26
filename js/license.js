class LicenseManager {
    constructor() {
        this.product = null;
        this.rateLimitCache = new Map();
        this.purchaseAttempts = new Map();
        this.isWaitingForPurchase = false;
        this.purchaseCheckInterval = null;
        this.currentUsername = null;
        this.init();
        this.setupVisibilityDetection();
    }

    async init() {
        const urlParams = new URLSearchParams(window.location.search);
        const productId = urlParams.get('id');
        const planId = urlParams.get('plan');

        if (!productId) {
            window.location.href = 'index.html';
            return;
        }

        this.productId = productId;
        this.planId = planId;

        await this.checkAuth();
        await this.loadProduct(productId, planId);
        this.renderProductInfo();
        this.renderAccountInfo();
        this.checkExistingPurchase();

        const pendingUsername = localStorage.getItem('pendingPurchaseUsername');
        if (pendingUsername) {
            console.log('Found pending purchase state for:', pendingUsername);
            this.showPendingPurchaseOption(pendingUsername);
        } else {
            console.log('No pending purchase state found, ready for user input');
        }
    }

    makeAuthenticatedRequest(url, options = {}) {
        const defaultOptions = {
            credentials: 'include',
            ...options
        };

        const authToken = localStorage.getItem('auth_token');
        if (authToken) {
            defaultOptions.headers = {
                ...defaultOptions.headers,
                'Authorization': `Bearer ${authToken}`
            };
        }

        return fetch(url, defaultOptions);
    }

    async checkAuth() {
        const storedUser = localStorage.getItem('user_data');
        if (storedUser) {
            try {
                this.user = JSON.parse(storedUser);
                this.renderAccountInfo();
            } catch (e) {
                localStorage.removeItem('user_data');
                localStorage.removeItem('auth_token');
            }
        }

        try {
            const response = await this.makeAuthenticatedRequest('http://localhost:5000/me');

            if (response.ok) {
                const data = await response.json();
                if (data.authenticated) {
                    this.user = data.user;
                    localStorage.setItem('user_data', JSON.stringify(data.user));
                    this.renderAccountInfo();
                    return;
                }
            }

            console.log('Server authentication failed, clearing cached data');
            this.user = null;
            localStorage.removeItem('user_data');
            localStorage.removeItem('auth_token');
            this.renderAccountInfo();
            
        } catch (error) {
            console.error('Auth check failed:', error);
            console.log('Network error during auth check, clearing cached data');
            this.user = null;
            localStorage.removeItem('user_data');
            localStorage.removeItem('auth_token');
            this.renderAccountInfo();
        }
    }

    async loadProduct(productId, planId) {
        try {
            let response;
            try {
                response = await fetch('http://localhost:5000/products');
            } catch (serverError) {
                console.warn('Server not available, loading from local file');
                response = await fetch('config/products.json');
            }

            const data = await response.json();

            const mainProduct = data.mainProducts.find(p => p.id === productId);
            if (!mainProduct) {
                console.error('Main product not found:', productId);
                throw new Error('Product not found');
            }

            if (planId) {
                this.product = data.products.find(p => p.id === planId);
                if (!this.product) {
                    console.error('Individual product not found:', planId);
                    throw new Error('Plan not found');
                }
            } else {
                if (mainProduct.variants && mainProduct.variants.length > 0) {
                    const firstVariantId = mainProduct.variants[0];
                    this.product = data.products.find(p => p.id === firstVariantId);
                } else {
                    console.error('No variants found for product:', productId);
                    throw new Error('No plans available');
                }
            }

            this.mainProduct = mainProduct;

            console.log('Loaded product:', this.product);
            console.log('Main product:', this.mainProduct);

        } catch (error) {
            console.error('Failed to load product:', error);
            window.location.href = 'index.html';
        }
    }

    renderProductInfo() {
        const container = document.getElementById('product-showcase');
        if (!container || !this.product || !this.mainProduct) return;

        const productBreadcrumbLink = document.getElementById('product-breadcrumb-link');
        const backLink = document.getElementById('back-link');
        if (productBreadcrumbLink && this.mainProduct) {
            productBreadcrumbLink.textContent = this.mainProduct.name;
            productBreadcrumbLink.href = `product.html?id=${this.mainProduct.id}`;
        }
        if (backLink && this.mainProduct) {
            backLink.href = `product.html?id=${this.mainProduct.id}`;
        }

        const mainImageSrc = this.mainProduct.mainImage || (this.mainProduct.images && this.mainProduct.images[0]) || '';

        container.innerHTML = `
            <div class="showcase-content">
                <img src="${mainImageSrc}" alt="${this.mainProduct.name}" class="product-image">
                <div class="product-info">
                    <div class="product-title">${this.mainProduct.name}</div>
                    <div class="product-plan">${this.product.name}</div>
                    <div class="product-duration">${this.product.duration}</div>
                    <div class="price-display">
                        <img src="icon/Robux.svg" alt="Robux Icon" class="price-icon">
                        <span class="price-value">${this.product.price}</span>
                    </div>
                </div>
            </div>
            <div class="purchase-section">
                <form id="form" class="purchase-form">
                    <div class="form-title">Enter Your Details</div>
                    
                    <div class="form-group">
                        <label class="form-label" id="usernameLabel" for="username">
                            Roblox Username
                        </label>
                        <input 
                            type="text" 
                            id="username" 
                            class="form-input"
                            placeholder="Enter your Roblox username..." 
                            required
                        >
                        <div id="username-hint" class="username-hint" style="display: none;">
                            ✓ Pre-filled from your account
                        </div>
                    </div>
                    
                    <button class="purchase-btn" id="continueButton" type="button" onclick="validatePurchase()">
                        Continue to Purchase
                    </button>
                </form>
            </div>
        `;

        if (backLink && this.productId) {
            backLink.href = `product.html?id=${this.productId}`;
        }

        this.setupAuthButtons();

        if (this.user && this.user.roblox_username) {
            const usernameInput = document.getElementById('username');
            const usernameHint = document.getElementById('username-hint');
            if (usernameInput) {
                usernameInput.value = this.user.roblox_username;
                usernameInput.style.borderColor = '#6366f1';
                usernameInput.title = 'Pre-filled from your account';

                if (usernameHint) {
                    usernameHint.style.display = 'block';
                }
            }
        }
    }

    setupAuthButtons() {
        const loginBtn = document.getElementById('login-btn');
        if (loginBtn) {
            const returnUrl = encodeURIComponent(window.location.href);
            loginBtn.href = `auth.html?return=${returnUrl}`;
        }

        const logoutBtn = document.getElementById('logout-btn');
        if (logoutBtn) {
            logoutBtn.onclick = this.logout.bind(this);
        }
    }

    renderAccountInfo() {
        const userInfo = document.getElementById('user-info');
        const authSection = document.getElementById('auth-section');
        const usernameDisplay = document.getElementById('username-display');

        if (this.user && userInfo && authSection && usernameDisplay) {
            usernameDisplay.textContent = this.user.username;
            userInfo.style.display = 'flex';
            authSection.style.display = 'none';
        } else if (userInfo && authSection) {
            userInfo.style.display = 'none';
            authSection.style.display = 'block';
        }
    }

    async logout() {
        try {
            await this.makeAuthenticatedRequest('http://localhost:5000/logout', {
                method: 'POST'
            });
            localStorage.removeItem('user_data');
            localStorage.removeItem('auth_token');
            window.location.reload();
        } catch (error) {
            console.error('Logout failed:', error);
            localStorage.removeItem('user_data');
            localStorage.removeItem('auth_token');
            window.location.reload();
        }
    }

    checkExistingPurchase() {
        const username = localStorage.getItem('lastUsername');
        const purchaseKey = `purchase_${this.product.id}_${username}`;
        const existingPurchase = localStorage.getItem(purchaseKey);

        if (existingPurchase && username) {
            const purchaseData = JSON.parse(existingPurchase);
            const now = Date.now();

            if (now - purchaseData.timestamp < 24 * 60 * 60 * 1000 && purchaseData.keyIssued) {
                document.getElementById('username').value = username;
            }
        }
    }



    isRateLimited(username) {
        const key = `${username}_${this.product.id}`;
        const lastAttempt = this.rateLimitCache.get(key);
        const now = Date.now();

        if (lastAttempt && now - lastAttempt < 5000) {
            return true;
        }

        this.rateLimitCache.set(key, now);
        return false;
    }

    trackPurchaseAttempt(username) {
        const key = `${username}_${this.product.id}`;
        const attempts = this.purchaseAttempts.get(key) || 0;
        this.purchaseAttempts.set(key, attempts + 1);
        localStorage.setItem('lastUsername', username);
    }

    trackSuccessfulPurchase(username) {
        const purchaseKey = `purchase_${this.product.id}_${username}`;
        localStorage.setItem(purchaseKey, JSON.stringify({
            keyIssued: true,
            timestamp: Date.now()
        }));
    }

    async validatePurchase() {
        const username = document.getElementById('username').value.trim();

        if (!username) {
            alert('Please enter your username.');
            return;
        }

        if (this.isRateLimited(username)) {
            this.updateStatus('Please wait 3 seconds before trying again.', 'orange');
            return;
        }

        this.currentUsername = username;
        localStorage.removeItem('pendingPurchaseUsername');
        localStorage.setItem('pendingPurchaseUsername', username);

        this.trackPurchaseAttempt(username);
        this.hideFormElements();
        this.updateStatus('Checking purchase status...', 'gray');

        try {
            await this.checkGamepassAndIssueKey(username);
        } catch (error) {
            this.handleValidationError(error);
        }
    }

    hideFormElements() {
        const elementsToHide = ['product-info', 'username', 'continueButton', 'usernameLabel'];
        elementsToHide.forEach(id => {
            const element = document.getElementById(id);
            if (element) element.style.display = 'none';
        });

        const purchaseForm = document.querySelector('.purchase-form');
        if (purchaseForm) {
            purchaseForm.style.display = 'none';
        }
    }

    async checkGamepassAndIssueKey(username) {
        try {
            console.log('Product object:', this.product);
            console.log('Gamepass ID:', this.product.gamepass_id);
            console.log('Gamepass URL:', this.product.gamepassUrl);

            const response = await this.fetchGamepassCheck(username, true);
            console.log('Purchase validation response:', response);

            if (response.hasGamepass) {
                if (response.keyIssued && response.key) {
                    this.updateStatus('Purchase Completed!', 'green');
                    this.displayKey(response.key);
                    this.trackSuccessfulPurchase(username);
                } else {
                    this.updateStatus(response.message || 'Error generating key', 'red');
                    this.displayRetryButton();
                }
            } else {
                this.updateStatus('Gamepass not owned. Redirecting to purchase...', 'blue');
                console.log('Opening gamepass URL:', this.product.gamepassUrl);
                if (this.product.gamepassUrl) {
                    window.open(this.product.gamepassUrl, '_blank');
                    this.updateStatus('Please complete your purchase in the new tab, then return here.', 'orange');
                    setTimeout(() => this.showPurchaseButton(), 2000);
                    const username = this.currentUsername || document.getElementById('username').value.trim();
                    if (username) {
                        localStorage.setItem('pendingPurchaseUsername', username);
                        this.currentUsername = username;
                        this.startPurchaseVerification(username);
                    }
                } else {
                    console.error('No gamepass URL found for product:', this.product);
                    this.showPurchaseButton();
                }
            }
        } catch (error) {
            this.handleValidationError(error);
        }
    }

    setupVisibilityDetection() {
        let wasHidden = false;
        let lastCheckTime = 0;

        const checkWithThrottle = () => {
            const now = Date.now();
            if (now - lastCheckTime < 500) {
                console.log('Check throttled, too recent');
                return;
            }
            lastCheckTime = now;
            console.log('User returned to tab, checking purchase status...');
            this.checkPurchaseOnReturn();
        };

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                wasHidden = true;
            } else if (wasHidden && this.isWaitingForPurchase && this.currentUsername) {
                wasHidden = false;
                setTimeout(checkWithThrottle, 100);
            }
        });
    }

    async checkPurchaseOnReturn() {
        if (!this.isWaitingForPurchase || !this.currentUsername) return;

        try {
            const response = await this.fetchGamepassCheck(this.currentUsername, true);

            if (response.hasGamepass) {
                this.stopPurchaseVerification();
                if (response.keyIssued && response.key) {
                    this.updateStatus('Welcome back! Purchase detected and completed!', 'green');
                    this.displayKey(response.key);
                    this.trackSuccessfulPurchase(this.currentUsername);
                } else {
                    this.updateStatus('Purchase detected, but there was an issue with key generation.', 'red');
                    this.displayRetryButton();
                }
            } else {
                this.showManualCheckOption();
            }
        } catch (error) {
            console.error('Error checking purchase on return:', error);
        }
    }

    showManualCheckOption() {
        const statusElement = document.getElementById('status');

        if (!statusElement.querySelector('.manual-check-btn')) {
            const manualCheckContainer = document.createElement('div');
            manualCheckContainer.className = 'manual-check-container';
            manualCheckContainer.style.marginTop = '20px';

            manualCheckContainer.innerHTML = `
                <p style="color: #666; margin-bottom: 15px;">
                    🔄 Returned from purchase? Click below to check if you've bought the gamepass:
                </p>
                <button class="btn manual-check-btn" onclick="licenseManager.manualPurchaseCheck()">
                    I have purchased the gamepass
                </button>
            `;

            statusElement.appendChild(manualCheckContainer);
        }
    }

    async manualPurchaseCheck() {
        if (!this.currentUsername) return;

        const manualCheckContainer = document.querySelector('.manual-check-container');
        if (manualCheckContainer) {
            manualCheckContainer.remove();
        }

        this.updateStatus('Checking your purchase...', 'gray');

        try {
            const response = await this.fetchGamepassCheck(this.currentUsername, true);

            if (response.hasGamepass) {
                this.stopPurchaseVerification();
                if (response.keyIssued && response.key) {
                    this.updateStatus('Purchase confirmed! Here\'s your key:', 'green');
                    this.displayKey(response.key);
                    this.trackSuccessfulPurchase(this.currentUsername);
                } else {
                    this.updateStatus('Purchase confirmed, but there was an issue with key generation.', 'red');
                    this.displayRetryButton();
                }
            } else {
                this.updateStatus('No purchase detected yet. Make sure you\'ve completed the purchase.', 'orange');
                setTimeout(() => this.showManualCheckOption(), 3000);
            }
        } catch (error) {
            this.updateStatus('Error checking purchase. Please try again.', 'red');
            setTimeout(() => this.showManualCheckOption(), 2000);
        }
    }

    stopPurchaseVerification() {
        this.isWaitingForPurchase = false;
        if (this.purchaseCheckInterval) {
            clearInterval(this.purchaseCheckInterval);
            this.purchaseCheckInterval = null;
        }
    }

    async startPurchaseVerification(username) {
        this.isWaitingForPurchase = true;
        this.currentUsername = username;
        localStorage.setItem('pendingPurchaseUsername', username);

        this.updateStatus('Waiting for purchase... We\'ll automatically detect when you return!', 'gray');

        setTimeout(() => this.showManualCheckOption(), 2000);

        return new Promise((resolve, reject) => {
            this.purchaseCheckInterval = setInterval(async () => {
                try {
                    const response = await this.fetchGamepassCheck(username);
                    console.log('Received response:', response);

                    if (response.hasGamepass) {
                        this.stopPurchaseVerification();
                        if (response.keyIssued) {
                            this.updateStatus('Purchase Completed!', 'green');
                            this.displayKey(response.key);
                            this.trackSuccessfulPurchase(username);
                        } else {
                            this.updateStatus('Key already claimed for this gamepass.', 'red');
                            this.displayRetryOption(username);
                        }
                        resolve();
                    }
                } catch (error) {
                    this.stopPurchaseVerification();
                    this.handleValidationError(error);
                    reject(error);
                }
            }, 5000);

            setTimeout(() => {
                if (this.isWaitingForPurchase) {
                    this.stopPurchaseVerification();
                    this.updateStatus('Auto-check timed out, but you can still check manually.', 'orange');
                    this.showManualCheckOption();
                    reject(new Error('Verification timeout'));
                }
            }, 90000);
        });
    }

    async fetchGamepassCheck(username, forceRefresh = false) {
        const maxRetries = 3;
        let retryCount = 0;

        while (retryCount < maxRetries) {
            try {
                const requestBody = {
                    username,
                    gamepass_id: this.product.gamepass_id
                };

                if (forceRefresh) {
                    requestBody.force_refresh = true;
                }

                console.log('Request body being sent:', requestBody);
                console.log('Product gamepass_id value:', this.product.gamepass_id);
                console.log('Product object keys:', Object.keys(this.product));

                const headers = {
                    'Content-Type': 'application/json',
                };

                const authToken = localStorage.getItem('auth_token');
                if (authToken) {
                    headers['Authorization'] = `Bearer ${authToken}`;
                }

                const response = await fetch('http://localhost:5000/check-gamepass', {
                    method: 'POST',
                    headers: headers,
                    credentials: 'include',
                    body: JSON.stringify(requestBody)
                });

                if (response.status === 429) {
                    const waitTime = Math.min(3000 * Math.pow(2, retryCount), 15000);
                    console.log(`Rate limit hit, waiting ${waitTime}ms...`);
                    await new Promise(resolve => setTimeout(resolve, waitTime));
                    retryCount++;
                    continue;
                }

                if (!response.ok) {
                    const errorData = await response.json();
                    if (errorData.shouldRetry && retryCount < maxRetries - 1) {
                        console.log(`Server suggested retry, attempt ${retryCount + 1}`);
                        retryCount++;
                        await new Promise(resolve => setTimeout(resolve, 2000));
                        continue;
                    }
                    throw new Error(errorData.error || 'Failed to check gamepass');
                }

                return await response.json();
            } catch (error) {
                retryCount++;
                if (retryCount >= maxRetries) {
                    throw error;
                }
                await new Promise(resolve => setTimeout(resolve, 1000));
            }
        }
    }

    displayKey(key) {
        const keyContainer = document.getElementById('keyContainer');
        const keyDisplay = document.getElementById('key-display');
        keyDisplay.textContent = key;
        keyContainer.style.display = 'block';

        const purchaseForm = document.querySelector('.purchase-form');
        if (purchaseForm) {
            purchaseForm.style.display = 'none';
        }
    }

    displayRetryOption(username) {
        const statusElement = document.getElementById('status');
        const retryContainer = document.createElement('div');
        retryContainer.className = 'retry-container';
        retryContainer.style.marginTop = '20px';

        retryContainer.innerHTML = `
            <p>To get a new key, please:</p>
            <ol>
                <li>Remove the gamepass from your Roblox inventory</li>
                <li>Re-purchase the gamepass</li>
                <li>Click the button below</li>
            </ol>
            <button class="btn retry-btn" onclick="licenseManager.manualCheck()">
                I have repurchased the gamepass
            </button>
        `;

        statusElement.appendChild(retryContainer);
    }

    displayRetryButton() {
        const statusElement = document.getElementById('status');
        const retryButton = document.createElement('button');
        retryButton.className = 'btn retry-btn';
        retryButton.innerText = 'Try Again';
        retryButton.onclick = () => window.location.reload();
        retryButton.style.marginTop = '10px';
        statusElement.appendChild(retryButton);
    }

    updateStatus(message, color) {
        const statusElement = document.getElementById('status');

        let statusClass = 'status-info';
        if (color === 'green') statusClass = 'status-success';
        else if (color === 'red') statusClass = 'status-error';
        else if (color === 'orange') statusClass = 'status-warning';
        else if (color === 'blue') statusClass = 'status-info';

        statusElement.innerHTML = `<div class="status-message ${statusClass}">${message}</div>`;
    }

    showManualCheckOption() {
        const statusElement = document.getElementById('status');
        const manualContainer = document.createElement('div');
        manualContainer.className = 'manual-check-container';
        manualContainer.style.marginTop = '20px';
        manualContainer.style.textAlign = 'center';

        const username = this.currentUsername || localStorage.getItem('pendingPurchaseUsername') || 'unknown';
        manualContainer.innerHTML = `
            <p style="margin-bottom: 15px;">Already purchased? Click below to check:</p>
            <button class="btn primary-btn" onclick="licenseManager.manualCheck()">
                I have purchased the gamepass
            </button>
        `;

        const existing = statusElement.querySelector('.manual-check-container');
        if (existing) {
            existing.remove();
        }

        statusElement.appendChild(manualContainer);
    }

    async manualCheck() {
        const username = this.currentUsername || localStorage.getItem('pendingPurchaseUsername');
        if (!username) {
            this.updateStatus('Error: No username found. Please refresh and try again.', 'red');
            return;
        }

        const manualContainer = document.querySelector('.manual-check-container');
        if (manualContainer) {
            manualContainer.remove();
        }

        this.updateStatus('Checking your purchase...', 'gray');

        try {
            const response = await this.fetchGamepassCheck(username, true);
            console.log('Manual check response:', response);

            if (response.hasGamepass) {
                if (response.keyIssued && response.key) {
                    this.updateStatus('Purchase confirmed! Here\'s your key:', 'green');
                    this.displayKey(response.key);
                    this.trackSuccessfulPurchase(username);
                } else {
                    this.updateStatus('Purchase confirmed, but there was an issue with key generation.', 'red');
                    this.displayRetryButton();
                }
            } else {
                this.updateStatus('No purchase detected yet. Make sure you\'ve completed the purchase.', 'orange');
                setTimeout(() => this.showManualCheckOption(), 3000);
            }
        } catch (error) {
            console.error('Manual check error:', error);
            this.updateStatus('Error checking purchase. Please try again.', 'red');
            setTimeout(() => this.showManualCheckOption(), 2000);
        }
    }



    async checkPendingPurchase() {
        const pendingUsername = localStorage.getItem('pendingPurchaseUsername');
        console.log('Checking for pending purchase, found username:', pendingUsername);
        if (pendingUsername) {
            console.log('Found pending purchase for username:', pendingUsername);
            this.currentUsername = pendingUsername;

            this.hideFormElements();
            this.updateStatus('Checking for completed purchase...', 'blue');

            try {
                const response = await this.fetchGamepassCheck(pendingUsername, true);
                console.log('Pending purchase check response:', response);

                if (response.hasGamepass && response.keyIssued) {
                    localStorage.removeItem('pendingPurchaseUsername');
                    this.updateStatus('Purchase Completed!', 'green');
                    this.displayKey(response.key);
                    this.trackSuccessfulPurchase(pendingUsername);
                } else if (!response.hasGamepass) {
                    localStorage.removeItem('pendingPurchaseUsername');
                    this.updateStatus('Gamepass not owned. Click below to purchase:', 'blue');
                    this.showPurchaseButton();
                } else {
                    this.updateStatus('Purchase detected but key not ready. We\'ll keep checking...', 'orange');
                    this.showManualCheckOption();
                    await this.startPurchaseVerification(pendingUsername);
                }
            } catch (error) {
                console.error('Error checking pending purchase:', error);
                this.updateStatus('Error checking purchase status. Please try manually.', 'red');
                this.showManualCheckOption();
            }
        }
    }

    trackSuccessfulPurchase(username) {
        console.log(`Purchase completed successfully for user: ${username}`);
        localStorage.removeItem('pendingPurchaseUsername');
    }

    clearPendingState() {
        localStorage.removeItem('pendingPurchaseUsername');
        console.log('Cleared pending purchase state');
        window.location.reload();
    }

    showPurchaseButton() {
        const statusElement = document.getElementById('status');

        const existingButton = statusElement.querySelector('.purchase-redirect-btn');
        if (existingButton) {
            existingButton.remove();
        }

        const purchaseContainer = document.createElement('div');
        purchaseContainer.className = 'purchase-redirect-container';
        purchaseContainer.style.marginTop = '20px';
        purchaseContainer.style.textAlign = 'center';

        purchaseContainer.innerHTML = `
            <p style="margin-bottom: 15px; color: #666;">You need to purchase the gamepass first:</p>
            <button class="btn primary-btn purchase-redirect-btn" onclick="licenseManager.redirectToPurchase()">
                <span class="btn-text">Purchase ${this.product.name}</span>
                <span class="btn-icon">🛒</span>
            </button>
            <p style="margin-top: 10px; font-size: 0.9rem; color: #888;">
                After purchasing, return to this page and we'll detect your purchase automatically.
            </p>
        `;

        statusElement.appendChild(purchaseContainer);
    }

    showPendingPurchaseOption(username) {
        const statusElement = document.getElementById('status');
        statusElement.innerHTML = `
            <div class="pending-purchase-notice" style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin: 0 0 10px 0; color: #856404;">⏳ Pending Purchase Detected</h3>
                <p style="margin: 0 0 15px 0; color: #856404;">
                    We found a pending purchase for username: <strong>${username}</strong>
                </p>
                <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                    <button class="btn primary-btn" onclick="licenseManager.checkPendingPurchase()">
                        Check if Purchase Completed
                    </button>
                    <button class="btn secondary-btn" onclick="licenseManager.clearPendingState()">
                        Start Fresh
                    </button>
                </div>
            </div>
        `;
    }

    redirectToPurchase() {
        if (this.product.gamepassUrl) {
            console.log('Opening gamepass URL:', this.product.gamepassUrl);
            const newWindow = window.open(this.product.gamepassUrl, '_blank');

            if (newWindow) {
                this.updateStatus('Please complete your purchase in the new tab, then return here.', 'orange');
                const username = this.currentUsername || document.getElementById('username').value.trim();
                if (username) {
                    localStorage.setItem('pendingPurchaseUsername', username);
                    this.currentUsername = username;
                    this.startPurchaseVerification(username);
                }
            } else {
                this.updateStatus('Popup blocked! Please copy this URL and open it manually:', 'orange');
                const statusElement = document.getElementById('status');
                const urlContainer = document.createElement('div');
                urlContainer.style.marginTop = '10px';
                urlContainer.innerHTML = `
                    <input type="text" value="${this.product.gamepassUrl}" readonly style="width: 100%; padding: 8px; margin: 5px 0;">
                    <button class="btn secondary-btn" onclick="navigator.clipboard.writeText('${this.product.gamepassUrl}')">Copy URL</button>
                `;
                statusElement.appendChild(urlContainer);
            }
        } else {
            console.error('No gamepass URL found for product:', this.product);
            alert('Error: Gamepass URL not found. Please contact support.');
        }
    }

    handleValidationError(error) {
        console.error('Validation error:', error);
        this.updateStatus(`Error: ${error.message}`, 'red');
        this.displayRetryButton();
    }
}

function copyKey() {
    const keyElement = document.getElementById('key');

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(keyElement.value).then(() => {
            showCopySuccess();
        }).catch(() => {
            fallbackCopy();
        });
    } else {
        fallbackCopy();
    }

    function fallbackCopy() {
        keyElement.select();
        keyElement.setSelectionRange(0, 99999);
        try {
            document.execCommand('copy');
            showCopySuccess();
        } catch (err) {
            console.error('Copy failed:', err);
        }
    }

    function showCopySuccess() {
        const copyBtn = document.querySelector('.copy-btn');
        const originalText = copyBtn.innerText;
        copyBtn.innerText = 'Copied!';
        copyBtn.style.backgroundColor = '#28a745';
        setTimeout(() => {
            copyBtn.innerText = originalText;
            copyBtn.style.backgroundColor = '';
        }, 2000);
    }
}

let licenseManager;

function validatePurchase() {
    licenseManager.validatePurchase();
}

document.addEventListener('DOMContentLoaded', () => {
    licenseManager = new LicenseManager();
});
