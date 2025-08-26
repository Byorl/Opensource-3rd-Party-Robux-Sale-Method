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
        const productId = urlParams.get('product');

        if (!productId) {
            window.location.href = 'index.html';
            return;
        }

        await this.loadProduct(productId);
        this.renderProductInfo();
        this.checkExistingPurchase();
    }

    async loadProduct(productId) {
        try {
            let response;
            try {
                response = await fetch('http://localhost:5000/products');
            } catch (serverError) {
                console.warn('Server not available, loading from local file');
                response = await fetch('config/products.json');
            }

            const data = await response.json();
            this.product = data.products.find(p => p.id === productId);

            if (!this.product) {
                throw new Error('Product not found');
            }
        } catch (error) {
            console.error('Failed to load product:', error);
            window.location.href = 'index.html';
        }
    }

    renderProductInfo() {
        const container = document.getElementById('product-info');
        if (!container || !this.product) return;

        container.innerHTML = `
            <h1 class="purchaseTitle">Purchase ${this.product.name}</h1>
            <div class="priceInfo">
                <div class="robuxContainer">
                    <img src="icon/Robux.svg" alt="Robux Icon" class="robuxIcon">
                    <span class="price">${this.product.price}</span>
                </div>
                <p class="duration">${this.product.duration}</p>
            </div>
        `;
    }

    checkExistingPurchase() {
        const username = localStorage.getItem('lastUsername');
        const purchaseKey = `purchase_${this.product.id}_${username}`;
        const existingPurchase = localStorage.getItem(purchaseKey);

        if (existingPurchase && username) {
            const purchaseData = JSON.parse(existingPurchase);
            const now = Date.now();

            if (now - purchaseData.timestamp < 24 * 60 * 60 * 1000) {
                document.getElementById('username').value = username;
                this.showExistingPurchaseWarning();
            }
        }
    }

    showExistingPurchaseWarning() {
        const statusElement = document.getElementById('status');
        statusElement.innerHTML = `
            <div class="warning">
                <p>⚠️ You recently purchased this license. If you continue, you won't get a new key unless you've removed the gamepass from your inventory.</p>
            </div>
        `;
        statusElement.style.color = 'orange';
    }

    isRateLimited(username) {
        const key = `${username}_${this.product.id}`;
        const lastAttempt = this.rateLimitCache.get(key);
        const now = Date.now();

        if (lastAttempt && now - lastAttempt < 30000) { 
            return true;
        }

        this.rateLimitCache.set(key, now);
        return false;
    }

    trackPurchaseAttempt(username) {
        const key = `${username}_${this.product.id}`;
        const attempts = this.purchaseAttempts.get(key) || 0;
        this.purchaseAttempts.set(key, attempts + 1);

        const purchaseKey = `purchase_${this.product.id}_${username}`;
        localStorage.setItem(purchaseKey, JSON.stringify({
            attempts: attempts + 1,
            timestamp: Date.now()
        }));
        localStorage.setItem('lastUsername', username);
    }

    async validatePurchase() {
        const username = document.getElementById('username').value.trim();

        if (!username) {
            alert('Please enter your username.');
            return;
        }

        if (this.isRateLimited(username)) {
            this.updateStatus('Please wait 30 seconds before trying again.', 'orange');
            return;
        }

        this.trackPurchaseAttempt(username);
        this.hideFormElements();
        this.updateStatus('Verifying Purchase... (This may take a minute)', 'gray');

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
    }

    async checkGamepassAndIssueKey(username) {
        try {
            const response = await this.fetchGamepassCheck(username);

            if (response.hasGamePass) {
                if (response.keyIssued && response.key) {
                    this.updateStatus('Purchase Completed!', 'green');
                    this.displayKey(response.key);
                } else {
                    this.updateStatus(response.message || 'Error generating key', 'red');
                    this.displayRetryButton();
                }
            } else {
                this.updateStatus('Gamepass not owned. Redirecting to purchase...', 'red');
                window.open(this.product.gamepassUrl, '_blank');
                await this.startPurchaseVerification(username);
            }
        } catch (error) {
            this.handleValidationError(error);
        }
    }

    setupVisibilityDetection() {
        let wasHidden = false;
        
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                wasHidden = true;
            } else if (wasHidden && this.isWaitingForPurchase && this.currentUsername) {
                console.log('User returned to tab, checking purchase status...');
                this.checkPurchaseOnReturn();
            }
        });

        let wasBlurred = false;
        window.addEventListener('blur', () => {
            wasBlurred = true;
        });
        
        window.addEventListener('focus', () => {
            if (wasBlurred && this.isWaitingForPurchase && this.currentUsername) {
                console.log('Window focused, checking purchase status...');
                setTimeout(() => this.checkPurchaseOnReturn(), 1000);
            }
        });
    }

    async checkPurchaseOnReturn() {
        if (!this.isWaitingForPurchase || !this.currentUsername) return;

        try {
            const response = await this.fetchGamepassCheck(this.currentUsername, true);

            if (response.hasGamePass) {
                this.stopPurchaseVerification();
                if (response.keyIssued && response.key) {
                    this.updateStatus('Welcome back! Purchase detected and completed!', 'green');
                    this.displayKey(response.key);
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

            if (response.hasGamePass) {
                this.stopPurchaseVerification();
                if (response.keyIssued && response.key) {
                    this.updateStatus('Purchase confirmed! Here\'s your key:', 'green');
                    this.displayKey(response.key);
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

        this.updateStatus('Waiting for purchase... We\'ll automatically detect when you return!', 'gray');

        setTimeout(() => this.showManualCheckOption(), 2000);

        return new Promise((resolve, reject) => {
            this.purchaseCheckInterval = setInterval(async () => {
                try {
                    const response = await this.fetchGamepassCheck(username);

                    if (response.hasGamePass) {
                        this.stopPurchaseVerification();
                        if (response.keyIssued) {
                            this.updateStatus('Purchase Completed!', 'green');
                            this.displayKey(response.key);
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
            }, 12000); 

            setTimeout(() => {
                if (this.isWaitingForPurchase) {
                    this.stopPurchaseVerification();
                    this.updateStatus('Auto-check timed out, but you can still check manually.', 'orange');
                    this.showManualCheckOption();
                    reject(new Error('Verification timeout'));
                }
            }, 300000);
        });
    }

    async fetchGamepassCheck(username, forceRefresh = false) {
        const maxRetries = 3;
        let retryCount = 0;

        while (retryCount < maxRetries) {
            try {
                const requestBody = {
                    username,
                    gamepass_id: this.product.gamepassId
                };

                if (forceRefresh) {
                    requestBody.force_refresh = true;
                }

                const response = await fetch('http://localhost:5000/check-gamepass', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(requestBody)
                });

                if (response.status === 429) {
                    const waitTime = Math.min(15000 * Math.pow(2, retryCount), 60000);
                    console.log(`Rate limit hit, waiting ${waitTime}ms...`);
                    await new Promise(resolve => setTimeout(resolve, waitTime));
                    retryCount++;
                    continue;
                }

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || 'Failed to check gamepass');
                }

                return await response.json();
            } catch (error) {
                retryCount++;
                if (retryCount >= maxRetries) {
                    throw error;
                }
                await new Promise(resolve => setTimeout(resolve, 5000));
            }
        }
    }

    displayKey(key) {
        const keyContainer = document.getElementById('keyContainer');
        const keyElement = document.getElementById('key');
        keyElement.value = key;
        keyContainer.style.display = 'block';
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
            <button class="btn retry-btn" onclick="licenseManager.checkGamepassAndIssueKey('${username}')">
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
        statusElement.innerHTML = `<p>${message}</p>`;
        statusElement.style.color = color;
        statusElement.style.textAlign = 'center';
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
