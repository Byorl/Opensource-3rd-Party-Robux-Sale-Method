class LicenseManager {
    constructor() {
        this.product = null;
        this.rateLimitCache = new Map();
        this.purchaseAttempts = new Map();
        this.init();
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
            const response = await fetch('config/products.json');
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
            
            // Check if purchase is recent (within 24 hours)
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
        
        if (lastAttempt && now - lastAttempt < 30000) { // 30 second cooldown
            return true;
        }
        
        this.rateLimitCache.set(key, now);
        return false;
    }

    trackPurchaseAttempt(username) {
        const key = `${username}_${this.product.id}`;
        const attempts = this.purchaseAttempts.get(key) || 0;
        this.purchaseAttempts.set(key, attempts + 1);
        
        // Store in localStorage for persistence
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
                if (response.keyIssued) {
                    this.updateStatus('Purchase Completed!', 'green');
                    this.displayKey(response.key);
                } else {
                    this.updateStatus(response.message, 'red');
                    this.displayRetryOption(username);
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

    async startPurchaseVerification(username) {
        this.updateStatus('Waiting for purchase... (This may take up to 5 minutes)', 'gray');

        return new Promise((resolve, reject) => {
            const checkInterval = setInterval(async () => {
                try {
                    const response = await this.fetchGamepassCheck(username);

                    if (response.hasGamePass) {
                        clearInterval(checkInterval);
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
                    clearInterval(checkInterval);
                    this.handleValidationError(error);
                    reject(error);
                }
            }, 8000); // Check every 8 seconds to reduce rate limiting

            // Timeout after 5 minutes
            setTimeout(() => {
                clearInterval(checkInterval);
                this.updateStatus('Purchase verification timed out. Please try again.', 'red');
                this.displayRetryButton();
                reject(new Error('Verification timeout'));
            }, 300000);
        });
    }

    async fetchGamepassCheck(username) {
        const maxRetries = 3;
        let retryCount = 0;

        while (retryCount < maxRetries) {
            try {
                const response = await fetch('http://localhost:5000/check-gamepass', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ 
                        username, 
                        gamepass_id: this.product.gamepassId 
                    })
                });

                if (response.status === 429) {
                    const waitTime = Math.min(15000 * Math.pow(2, retryCount), 60000); // Exponential backoff
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
    keyElement.select();
    keyElement.setSelectionRange(0, 99999);
    document.execCommand('copy');
    
    const copyBtn = document.querySelector('.copy-btn');
    const originalText = copyBtn.innerText;
    copyBtn.innerText = 'Copied!';
    setTimeout(() => {
        copyBtn.innerText = originalText;
    }, 2000);
}

// Global functions for onclick handlers
let licenseManager;

function validatePurchase() {
    licenseManager.validatePurchase();
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    licenseManager = new LicenseManager();
});
