class LicenseManager {
    constructor() {
        this.product = null;
        this.mainProduct = null;
        this.productId = null;
        this.planId = null;
        this.user = null;
        this.isAuthenticated = false;

        this.currentUsername = null;
        this.isCheckingPurchase = false;
        this.purchaseCompleted = false;
        this.rateLimitCache = new Map();
        this.purchaseAttempts = new Map();
        this.state = 'idle';
        this.pendingSession = null; 

        this.init();
    }

    async init() {
        console.log('LicenseManager.init() called');
        const urlParams = new URLSearchParams(window.location.search);
        const productId = urlParams.get('id');
        const planId = urlParams.get('plan');

        if (!productId) {
            window.location.href = 'index.html';
            return;
        }

        this.productId = productId;
        this.planId = planId;

        console.log('Checking auth...');
        await this.checkAuth();
        console.log('Loading product...');
        await this.loadProduct(productId, planId);
        console.log('Rendering product info...');
        this.renderProductInfo();
        console.log('Rendering account info...');
        this.renderAccountInfo();
        console.log('Checking existing purchase...');
        this.checkExistingPurchase();
        console.log('Ready (no pending purchase revival).');
    }

    makeAuthenticatedRequest(url, options = {}) {
        const defaultOptions = {
            credentials: 'include',
            ...options
        };

        return fetch(url, defaultOptions);
    }

    async checkAuth() {
        const storedUser = localStorage.getItem('user_data');
        if (storedUser) {
            try {
                this.user = JSON.parse(storedUser);
                this.isAuthenticated = true;
                this.renderAccountInfo();
            } catch (e) {
                localStorage.removeItem('user_data');
            }
        }

        try {
            const response = await this.makeAuthenticatedRequest('/me');

            if (response.ok) {
                const data = await response.json();
                if (data.authenticated) {
                    this.user = data.user;
                    this.isAuthenticated = true;
                    localStorage.setItem('user_data', JSON.stringify(data.user));
                    this.renderAccountInfo();
                    return;
                }
            }

            console.log('Server authentication failed, clearing cached data');
            this.user = null;
            this.isAuthenticated = false;
            localStorage.removeItem('user_data');
            this.renderAccountInfo();
            
        } catch (error) {
            console.error('Auth check failed:', error);
            console.log('Network error during auth check, clearing cached data');
            this.user = null;
            this.isAuthenticated = false;
            localStorage.removeItem('user_data');
            this.renderAccountInfo();
        }
    }

    async loadProduct(productId, planId) {
        try {
            let response;
            try {
                response = await fetch('/products');
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
        console.log('renderProductInfo() called');
        const container = document.getElementById('product-showcase');
        if (!container || !this.product || !this.mainProduct) {
            console.log('Missing container, product, or mainProduct');
            return;
        }

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

        console.log('Creating form HTML...');
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
            <div id="status" class="status-container" style="display: none;"></div>
            <div id="keyContainer" class="key-result" style="display:none;">
                <div class="key-title">🎉 Purchase Successful!</div>
                <div class="key-display" id="key-display"></div>
                <button class="copy-btn" onclick="copyKey()">
                    Copy License Key
                </button>
            </div>
        `;

        console.log('Form HTML created, setting up auth buttons...');
        if (backLink && this.productId) {
            backLink.href = `product.html?id=${this.productId}`;
        }

        this.setupAuthButtons();

        console.log('Checking if user has roblox_username...');
        if (this.user && this.user.roblox_username) {
            console.log('User has roblox_username:', this.user.roblox_username);
            const usernameInput = document.getElementById('username');
            const usernameHint = document.getElementById('username-hint');
            if (usernameInput) {
                console.log('Setting username input value');
                usernameInput.value = this.user.roblox_username;
                usernameInput.style.borderColor = '#6366f1';
                usernameInput.title = 'Pre-filled from your account';

                if (usernameHint) {
                    console.log('Showing username hint');
                    usernameHint.style.display = 'block';
                }
            }
        } else {
            console.log('User does not have roblox_username or is not logged in');
        }
        
        setTimeout(() => {
            const form = document.getElementById('form');
            const usernameInput = document.getElementById('username');
            const continueButton = document.getElementById('continueButton');
            const purchaseSection = document.querySelector('.purchase-section');
            const statusElement = document.getElementById('status');
            console.log('Form elements after renderProductInfo():');
            console.log('- Form:', form, 'display:', form ? form.style.display : 'not found');
            console.log('- Username input:', usernameInput, 'display:', usernameInput ? usernameInput.style.display : 'not found');
            console.log('- Continue button:', continueButton, 'display:', continueButton ? continueButton.style.display : 'not found');
            console.log('- Purchase section:', purchaseSection, 'display:', purchaseSection ? purchaseSection.style.display : 'not found');
            console.log('- Status element:', statusElement, 'display:', statusElement ? statusElement.style.display : 'not found');
            
            if (form && form.style.display === 'none') {
                console.log('Form was hidden, making it visible');
                form.style.display = 'block';
            }
            if (purchaseSection && purchaseSection.style.display === 'none') {
                console.log('Purchase section was hidden, making it visible');
                purchaseSection.style.display = 'block';
            }
            if (statusElement && statusElement.style.display === 'block') {
                console.log('Status was visible on page load, hiding it');
                statusElement.style.display = 'none';
                statusElement.innerHTML = '';
            }
        }, 100);
        
        console.log('renderProductInfo() completed');
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
        const navHistoryLink = document.getElementById('nav-history-link');

        if (this.user && userInfo && authSection && usernameDisplay) {
            usernameDisplay.textContent = this.user.username;
            userInfo.style.display = 'flex';
            authSection.style.display = 'none';
            if (navHistoryLink) navHistoryLink.style.display = 'inline';
        } else if (userInfo && authSection) {
            userInfo.style.display = 'none';
            authSection.style.display = 'block';
            if (navHistoryLink) navHistoryLink.style.display = 'none';
        }
    }

    async logout() {
        try {
            await this.makeAuthenticatedRequest('/logout', {
                method: 'POST'
            });
            localStorage.removeItem('user_data');
            window.location.reload();
        } catch (error) {
            console.error('Logout failed:', error);
            localStorage.removeItem('user_data');
            window.location.reload();
        }
    }

    checkExistingPurchase() {
        if (!this.product) return;
        const username = localStorage.getItem('lastUsername');
        if (!username) return;
        const purchaseKey = `purchase_${this.product.id}_${username}`;
        try {
            const existingPurchase = localStorage.getItem(purchaseKey);
            if (!existingPurchase) return;
            const purchaseData = JSON.parse(existingPurchase);
            const now = Date.now();
            if (now - purchaseData.timestamp < 24 * 60 * 60 * 1000 && purchaseData.keyIssued) {
                const usernameInput = document.getElementById('username');
                if (usernameInput) usernameInput.value = username;
            }
        } catch (e) { /* ignore */ }
    }

    checkTransactionClaimed(transactionId) {
        if (!transactionId) return false;
        try {
            const claimedTransactions = JSON.parse(localStorage.getItem('claimed_transactions') || '[]');
            return claimedTransactions.includes(transactionId);
        } catch (e) {
            return false;
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

    trackSuccessfulPurchase(username, transactionId) {
        const purchaseKey = `purchase_${this.product.id}_${username}`;
        localStorage.setItem(purchaseKey, JSON.stringify({
            keyIssued: true,
            timestamp: Date.now(),
            transactionId: transactionId
        }));
        
        if (transactionId) {
            const claimedTransactions = JSON.parse(localStorage.getItem('claimed_transactions') || '[]');
            if (!claimedTransactions.includes(transactionId)) {
                claimedTransactions.push(transactionId);
                localStorage.setItem('claimed_transactions', JSON.stringify(claimedTransactions));
            }
        }
    }

    async validatePurchase() {
        const usernameInput = document.getElementById('username');
        const username = usernameInput ? usernameInput.value.trim() : '';
        if (!username) {
            alert('Please enter your username.');
            return;
        }
        if (this.isRateLimited(username)) {
            this.updateStatus('Please wait 3 seconds before trying again.', 'orange');
            return;
        }
        this.currentUsername = username;
        this.trackPurchaseAttempt(username);
        this.hideFormElements();
        this.showPurchasePrompt(); 
        
        try { 
            await this.startPurchaseSession(username);
            this.updateStatus('Ready for purchase verification. Buy the gamepass, then click the "I Have Purchased The Gamepass" button below.', 'blue', true);
            const purchaseContainer = document.querySelector('.purchase-container');
            if (purchaseContainer) {
                this.showManualCheckButton(purchaseContainer);
            }
        } catch(e){ 
            console.warn('startPurchaseSession failed:', e.message);
            this.updateStatus('Ready for purchase verification. Buy the gamepass, then click the "I Have Purchased The Gamepass" button below.', 'blue', true);
            const purchaseContainer = document.querySelector('.purchase-container');
            if (purchaseContainer) {
                this.showManualCheckButton(purchaseContainer);
            }
        }
        
    }

    hideFormElements() {
        const purchaseSection = document.querySelector('.purchase-section');
        if (purchaseSection) purchaseSection.style.display = 'none';
    }

    async checkGamepassAndIssueKey(username) {
        if (this.isCheckingPurchase) return;
        this.isCheckingPurchase = true;
        try {
            const response = await this.fetchGamepassCheck(username, true);
            if (response.needStart) {
                try {
                    await this.startPurchaseSession(username);
                    const retry = await this.fetchGamepassCheck(username, true);
                    if (retry.transactionId && this.checkTransactionClaimed(retry.transactionId)) {
                        this.updateStatus('This purchase has already been claimed. Please check your purchase history.', 'orange');
                        if (retry.key) {
                            this.showExistingKeyOption(retry.key, retry.expiryDate);
                        }
                        return;
                    }
                    this._handleCheckResponse(username, retry);
                } catch (e) {
                    this.updateStatus('Login required before verifying purchase.', 'red');
                }
                return;
            }
            if (response.transactionId && this.checkTransactionClaimed(response.transactionId)) {
                this.updateStatus('This purchase has already been claimed. Please check your purchase history.', 'orange');
                if (response.key) {
                    this.showExistingKeyOption(response.key, response.expiryDate);
                }
                return;
            }
            this._handleCheckResponse(username, response);
        } catch (e) {
            console.error('checkGamepassAndIssueKey error:', e);
            this.updateStatus('Error validating purchase. You can still try manual check after buying.', 'red');
        } finally {
            this.isCheckingPurchase = false;
        }
    }

    _handleCheckResponse(username, response){
        if (!response) return;
        if (!response.hasGamepass) {
            return;
        }
        if (response.transactionId && this.checkTransactionClaimed(response.transactionId)) {
            this.updateStatus('This purchase has already been claimed. Please check your purchase history.', 'orange');
            if (response.key) {
                this.showExistingKeyOption(response.key, response.expiryDate);
            }
            return;
        }
        const statusElement = document.getElementById('status');
        if (statusElement) statusElement.innerHTML = '';
        if (response.keyIssued && response.key) {
            if (response.isNewKey) {
                this.updateStatus('Purchase Completed!', 'green');
                this.displayKey(response.key);
                this.trackSuccessfulPurchase(username, response.transactionId);
            } else {
                this.updateStatus('You already claimed this key earlier. Click below to view it again.', 'blue');
                this.showExistingKeyOption(response.key, response.expiryDate);
            }
        } else {
            this.updateStatus(response.message || 'Error generating key', 'red');
            this.displayRetryButton();
        }
    }
    

    setupVisibilityDetection() {}
    checkPurchaseOnReturn() {}

    showManualCheckButton(parent) {
        if (parent.querySelector('.manual-check-container')) return;
        const div = document.createElement('div');
        div.className = 'manual-check-container action-card';
        div.style.textAlign = 'center';
        div.innerHTML = `
            <h3 style="margin:0 0 8px 0;font-size:1rem;color:#fff;">Already Purchased?</h3>
            <p style="margin:0 0 14px 0; color:#cbd5e1;font-size:0.85rem;">If you've just bought it, click below to verify and get your key.</p>
            <button class="btn secondary-btn" onclick="licenseManager.manualCheck()">I Have Purchased The Gamepass</button>        `;
        parent.appendChild(div);
    }

    stopPurchaseVerification() {}
    startPurchaseVerification() {}

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

                const response = await fetch('/check-gamepass', {
                    method: 'POST',
                    headers: headers,
                    credentials: 'include',
                    body: JSON.stringify(requestBody)
                });

                if (response.status === 429) {
                    const body = await response.json().catch(()=>({}));
                    if (body && body.retryAfter) {
                        this.beginRetryCountdown(body.retryAfter);
                    }
                    return body;
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

    startPendingPurchase() { }

    showRepurchaseNeeded(priorKeyCount) {
        let statusElement = document.getElementById('status');

        if (!statusElement) {
            console.log('Status element not found in showRepurchaseNeeded, creating it...');
            const container = document.getElementById('product-showcase');
            if (container) {
                const statusDiv = document.createElement('div');
                statusDiv.id = 'status';
                statusDiv.className = 'status-container';
                statusDiv.style.display = 'none';
                container.appendChild(statusDiv);
                statusElement = statusDiv;
            } else {
                console.error('Could not find product-showcase container to create status element');
                return;
            }
        }

        const container = document.createElement('div');
        container.className = 'repurchase-needed';
        container.style.marginTop = '16px';
        container.style.padding = '16px';
        container.style.border = '1px solid #ddd';
        container.style.borderRadius = '8px';
        container.style.background = '#fff';
        const historyLink = this.isAuthenticated ? `<p style="margin:8px 0 0 0;font-size:0.8rem;color:#555">You have already claimed <strong>${priorKeyCount}</strong> key${priorKeyCount===1?'':'s'} for this product. <a href="history.html" style="text-decoration:underline">View purchase history</a>.</p>` : `<p style="margin:8px 0 0 0;font-size:0.8rem;color:#555">You have already claimed keys for this product previously.</p>`;
        container.innerHTML = `
            <h3 style="margin:0 0 8px 0;font-size:1rem;">No New Purchase Detected</h3>
            <p style="margin:0 0 8px 0;font-size:0.9rem;color:#444">To obtain another key you must remove (delete) the gamepass from your Roblox inventory and buy it again. After buying, return here and we'll detect the new transaction.</p>
            ${historyLink}
            <div style="margin-top:12px;text-align:center;">
                <button class="btn primary-btn" onclick="licenseManager.redirectToPurchase()">Re-Purchase Now</button>
            </div>
        `;
        statusElement.innerHTML = '';
        statusElement.appendChild(container);
    }

    displayKey(key) {
        const keyContainer = document.getElementById('keyContainer');
        const keyDisplay = document.getElementById('key-display');
        if (!keyContainer || !keyDisplay) return;
        if (keyContainer.getAttribute('data-shown') === 'true') return;
        keyDisplay.textContent = key;
        keyContainer.style.display = 'block';
        keyContainer.setAttribute('data-shown','true');
        const statusElement = document.getElementById('status');
        if (statusElement) statusElement.style.display = 'none';
        this.purchaseCompleted = true;
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
        let statusElement = document.getElementById('status');

        if (!statusElement) {
            console.log('Status element not found in displayRetryButton, creating it...');
            const container = document.getElementById('product-showcase');
            if (container) {
                const statusDiv = document.createElement('div');
                statusDiv.id = 'status';
                statusDiv.className = 'status-container';
                statusDiv.style.display = 'none';
                container.appendChild(statusDiv);
                statusElement = statusDiv;
            } else {
                console.error('Could not find product-showcase container to create status element');
                return;
            }
        }

        const retryButton = document.createElement('button');
        retryButton.className = 'btn retry-btn';
        retryButton.innerText = 'Try Again';
        retryButton.onclick = () => window.location.reload();
        retryButton.style.marginTop = '10px';
        statusElement.appendChild(retryButton);
    }

    updateStatus(message, color, persistent = true) {
        let statusElement = document.getElementById('status');
        if (!statusElement) {
            const container = document.getElementById('product-showcase');
            if (!container) return;
            statusElement = document.createElement('div');
            statusElement.id = 'status';
            statusElement.className = 'status-container';
            container.appendChild(statusElement);
        }

        let messageZone = statusElement.querySelector('.status-messages');
        if (!messageZone) {
            messageZone = document.createElement('div');
            messageZone.className = 'status-messages';
            messageZone.setAttribute('aria-live','polite');
            statusElement.appendChild(messageZone);
        }

        const statusClassMap = { green: 'status-success', red: 'status-error', orange: 'status-warning', blue: 'status-info', gray: 'status-info' };
        const statusClass = statusClassMap[color] || 'status-info';

        messageZone.innerHTML = `<div class="status-message ${statusClass}">${message}</div>`;
        
        if (persistent === false) {
        } else if (/Verifying your purchase/i.test(message)) {
        } else if (/Still not seeing a purchase|Make sure you completed the Robux purchase/i.test(message)) {
        }
        
        statusElement.style.display = 'block';
    }

    showExistingKeyOption(key, expiry) {
        let statusElement = document.getElementById('status');

        if (!statusElement) {
            console.log('Status element not found in showExistingKeyOption, creating it...');
            const container = document.getElementById('product-showcase');
            if (container) {
                const statusDiv = document.createElement('div');
                statusDiv.id = 'status';
                statusDiv.className = 'status-container';
                statusDiv.style.display = 'none';
                container.appendChild(statusDiv);
                statusElement = statusDiv;
            } else {
                console.error('Could not find product-showcase container to create status element');
                return;
            }
        }

        const existing = document.getElementById('existing-key-reveal');
        if (existing) existing.remove();
        const wrap = document.createElement('div');
        wrap.id = 'existing-key-reveal';
        wrap.style.marginTop = '16px';
        wrap.style.textAlign = 'center';
        const safeKey = key.replace(/`/g, '\`');
        const expiryHtml = expiry ? `<div style="margin-top:8px;font-size:0.75rem;color:#888">Expires: ${expiry}</div>` : '';
        wrap.innerHTML = `
            <button class="btn" style="background:#374151" onclick="(function(btn){
                var kc=document.getElementById('keyContainer');
                if(kc.getAttribute('data-shown')==='true'){ kc.scrollIntoView({behavior:'smooth'}); return; }
                licenseManager.displayKey('${safeKey}');
                btn.textContent='Key Shown';
            })(this)">View Existing Key</button>
            ${expiryHtml}
        `;
    }


    async manualCheck() {
        const username = this.currentUsername;
        if (!username) {
            this.updateStatus('No username present. Refresh and try again.', 'red');
            return;
        }
        if (this.isCheckingPurchase) return;
        this.isCheckingPurchase = true;
        this.clearAutoCheck();
        this.updateStatus('Verifying your purchase...', 'gray', true);
        try {
            if (!this.pendingSession || this.pendingSession.username.toLowerCase() !== username.toLowerCase()) {
                await this.startPurchaseSession(username).catch(()=>{});
            }
            const response = await this.fetchGamepassCheck(username, true);
            if (response.transactionId && this.checkTransactionClaimed(response.transactionId)) {
                this.updateStatus('This purchase has already been claimed. Please check your purchase history.', 'orange');
                if (response.key) {
                    this.showExistingKeyOption(response.key, response.expiryDate);
                }
                return;
            }
            if (response.needStart) {
                if (!this.pendingSession || this.pendingSession.username.toLowerCase() !== username.toLowerCase()) {
                    await this.startPurchaseSession(username).catch(()=>{});
                }
                const retry = await this.fetchGamepassCheck(username, true);
                if (retry.transactionId && this.checkTransactionClaimed(retry.transactionId)) {
                    this.updateStatus('This purchase has already been claimed. Please check your purchase history.', 'orange');
                    if (retry.key) {
                        this.showExistingKeyOption(retry.key, retry.expiryDate);
                    }
                    return;
                }
                this._handleManualCheckResponse(username, retry);
                return;
            }
            this._handleManualCheckResponse(username, response);
        } catch (e) {
            console.error('Manual check error:', e);
            this.updateStatus('Error checking purchase. Please try again in a moment.', 'red');
        } finally {
            this.isCheckingPurchase = false;
        }
    }

    _handleManualCheckResponse(username, response){
        if (!response) return;
        if (response.rate_limited || response.status === 'Rate Limited') {
            this.updateStatus('Rate limited by Roblox or server. Please wait 5-10 seconds then press "I Have Purchased The Gamepass" again.', 'orange');
            return;
        }
        if (!response.hasGamepass) {
            if (response.hadPreviousKeys) {
                this.showRepurchaseNeeded(response.priorKeyCount || 0);
            } else {
                this.updateStatus('Still not seeing a purchase. Make sure you completed the Robux purchase. Roblox may take 10-30 seconds to register your purchase. Please wait and try again.', 'orange', false); 
                
                const purchaseContainer = document.querySelector('.purchase-container');
                if (purchaseContainer) {
                    const retryDiv = document.createElement('div');
                    retryDiv.className = 'retry-container';
                    retryDiv.style.marginTop = '16px';
                    retryDiv.style.textAlign = 'center';
                    purchaseContainer.appendChild(retryDiv);
                }
            }
            return;
        }
        if (response.transactionId && this.checkTransactionClaimed(response.transactionId)) {
            this.updateStatus('This purchase has already been claimed. Please check your purchase history.', 'orange');
            if (response.key) {
                this.showExistingKeyOption(response.key, response.expiryDate);
            }
            return;
        }
        if (response.keyIssued && response.key) {
            this.updateStatus('Purchase confirmed! Here\'s your key:', 'green');
            this.displayKey(response.key);
            this.trackSuccessfulPurchase(username, response.transactionId);
        } else {
            this.updateStatus('Purchase confirmed, but key generation failed.', 'red');
            this.displayRetryButton();
        }
    }



    trackSuccessfulPurchase(username, transactionId) {
        const purchaseKey = `purchase_${this.product.id}_${username}`;
        localStorage.setItem(purchaseKey, JSON.stringify({
            keyIssued: true,
            timestamp: Date.now(),
            transactionId: transactionId
        }));
        
        if (transactionId) {
            const claimedTransactions = JSON.parse(localStorage.getItem('claimed_transactions') || '[]');
            if (!claimedTransactions.includes(transactionId)) {
                claimedTransactions.push(transactionId);
                localStorage.setItem('claimed_transactions', JSON.stringify(claimedTransactions));
            }
        }
    }

    showPurchasePrompt() {
        let statusElement = document.getElementById('status');
        if (!statusElement) {
            const container = document.getElementById('product-showcase');
            if (!container) return;
            statusElement = document.createElement('div');
            statusElement.id = 'status';
            statusElement.className = 'status-container';
            container.appendChild(statusElement);
        }
        statusElement.innerHTML = '';

        const actionsWrapper = document.createElement('div');
        actionsWrapper.className = 'actions-grid';
        actionsWrapper.style.display = 'flex';
        actionsWrapper.style.flexDirection = 'column';
        actionsWrapper.style.gap = '18px';

        const purchaseDiv = document.createElement('div');
        purchaseDiv.className = 'purchase-redirect-container action-card';
        purchaseDiv.style.textAlign = 'center';
        purchaseDiv.innerHTML = `
            <h3 style="margin:0 0 8px 0;font-size:1rem;color:#fff;">Step 1: Purchase</h3>
            <p style="margin:0 0 14px 0; color:#cbd5e1;font-size:0.85rem;">Buy the required gamepass to generate your license key.</p>
            <button class="btn primary-btn" onclick="licenseManager.redirectToPurchase()">
                <span class="btn-text">Purchase ${this.product.name}</span>
                <span class="btn-icon">🛒</span>
            </button>
        `;

        actionsWrapper.appendChild(purchaseDiv);
        statusElement.appendChild(actionsWrapper);
        this.showManualCheckButton(actionsWrapper);

        statusElement.style.display = 'block';
        this.state = 'prompting';
    }

    redirectToPurchase() {
        if (!this.product || !this.product.gamepassUrl) {
            this.updateStatus('Gamepass URL not configured.', 'red');
            return;
        }
        const win = window.open(this.product.gamepassUrl, '_blank');
        if (win) {
            this.updateStatus('After completing the purchase, return here and click the verification button.', 'orange');
        } else {
            this.updateStatus('Popup blocked! Copy the URL below and open it manually.', 'orange');
            const statusElement = document.getElementById('status');
            if (statusElement) {
                const urlDiv = document.createElement('div');
                urlDiv.style.marginTop = '10px';
                urlDiv.innerHTML = `
                    <input type="text" value="${this.product.gamepassUrl}" readonly style="width:100%;padding:8px;margin:6px 0;">
                    <button class="btn secondary-btn" onclick="navigator.clipboard.writeText('${this.product.gamepassUrl}')">Copy URL</button>
                `;
                statusElement.appendChild(urlDiv);
            }
        }
    }

    handleValidationError(error) {
        console.error('Validation error:', error);
        this.updateStatus(`Error: ${error.message}`, 'red');
        this.displayRetryButton();
    }

    async startPurchaseSession(username){
        if (!this.product || !this.product.id) return;
        if (this.pendingSession && this.pendingSession.username.toLowerCase() === username.toLowerCase() && this.pendingSession.productId === this.product.id) {
            return { started: true, started_at: this.pendingSession.started_at, reused: true };
        }
        const headers = { 'Content-Type': 'application/json' };
        const body = { roblox_username: username, product_id: this.product.id };
        let resp;
        try {
            resp = await fetch('/start-purchase', {
                method: 'POST',
                credentials: 'include',
                headers,
                body: JSON.stringify(body)
            });
        } catch(e){
            throw new Error('Network');
        }
        if (resp.status === 401) throw new Error('AUTH');
        if (!resp.ok) throw new Error('Failed to start');
        const js = await resp.json();
        if (js && js.started_at) {
            this.pendingSession = { username, productId: this.product.id, started_at: js.started_at };
        }
        return js;
    }

    beginRetryCountdown(seconds){
        const btn = document.querySelector('.manual-check-container button');
        if (!btn) return;
        let remaining = Math.ceil(seconds);
        const original = btn.textContent;
        btn.disabled = true;
        const tick = ()=>{
            if (remaining <= 0) {
                btn.disabled = false;
                btn.textContent = original;
                return;
            }
            btn.textContent = original + ` (${remaining}s)`;
            remaining -= 1;
            setTimeout(tick,1000);
        };
        tick();
    }

    renderPendingSessionIndicator(){
        // No longer used
    }

    scheduleAutoCheck(reset=false){
        // No longer used
    }

    clearAutoCheck(){
        // No longer used
    }
}

function copyKey() {
    const keyDisplay = document.getElementById('key-display');
    if (!keyDisplay) return;
    const text = keyDisplay.textContent.trim();
    const doSuccess = () => {
        const copyBtn = document.querySelector('.copy-btn');
        if (!copyBtn) return;
        const original = copyBtn.innerText;
        copyBtn.innerText = 'Copied!';
        copyBtn.style.backgroundColor = '#16a34a';
        setTimeout(()=>{ copyBtn.innerText = original; copyBtn.style.backgroundColor=''; },1500);
    };
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(doSuccess).catch(()=>{
            try {
                const ta = document.createElement('textarea');
                ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); doSuccess();
            } catch(e) { console.error('Copy failed', e); }
        });
    }
}

let licenseManager;

function validatePurchase() {
    licenseManager.validatePurchase();
}

document.addEventListener('DOMContentLoaded', () => { licenseManager = new LicenseManager(); });

function validatePurchase() { licenseManager.validatePurchase(); }
