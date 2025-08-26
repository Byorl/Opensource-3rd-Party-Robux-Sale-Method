class ProductManager {
    constructor() {
        this.products = [];
        this.init();
    }

    async init() {
        await this.loadProducts();
        this.renderProducts();
    }

    async loadProducts() {
        try {
            let response;
            try {
                response = await fetch('http://localhost:5000/products');
            } catch (serverError) {
                console.warn('Server not available, loading from local file');
                response = await fetch('config/products.json');
            }

            const data = await response.json();
            this.products = data.products;
        } catch (error) {
            console.error('Failed to load products:', error);
            this.products = [];
        }
    }

    renderProducts() {
        const container = document.getElementById('products-container');
        if (!container) return;

        if (this.products.length === 0) {
            container.innerHTML = `
                <div class="loading-container">
                    <div class="loading"></div>
                    <p>Loading products...</p>
                </div>
            `;
            return;
        }

        const buttonsHtml = this.products.map(product => {
            const stockCount = product.stock || 0;
            const stockClass = stockCount === 0 ? 'out-of-stock' : stockCount < 10 ? 'low-stock' : 'in-stock';
            const stockText = stockCount === 0 ? 'Out of Stock' : `${stockCount} Available`;
            const stockIcon = stockCount === 0 ? '❌' : stockCount < 10 ? '⚠️' : '✅';
            
            return `
                <div class="product-item ${stockClass}" data-product-id="${product.id}">
                    <div class="product-header">
                        <h3 class="product-name">${product.name}</h3>
                        <div class="product-duration">${product.duration || 'Access Duration'}</div>
                    </div>
                    
                    <div class="product-body">
                        <div class="price-section">
                            <div class="price-label">Price</div>
                            <div class="price-box">
                                <img src="icon/Robux.svg" alt="Robux Icon" class="robux-icon">
                                <span class="price">${product.price}</span>
                            </div>
                        </div>
                        
                        <div class="stock-section">
                            <div class="stock-label">Availability</div>
                            <div class="stock-indicator ${stockClass}">
                                <span class="stock-icon">${stockIcon}</span>
                                <span class="stock-text">${stockText}</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="product-footer">
                        <button class="btn primary-btn" onclick="redirectToLicense('${product.id}')" ${stockCount === 0 ? 'disabled' : ''}>
                            <span class="btn-text">${stockCount === 0 ? 'Out of Stock' : 'Purchase License'}</span>
                            <span class="btn-icon">${stockCount === 0 ? '🚫' : '🚀'}</span>
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div class="products-grid">
                ${buttonsHtml}
            </div>
        `;

        this.addProductAnimations();
    }

    addProductAnimations() {
        const productItems = document.querySelectorAll('.product-item');
        productItems.forEach((item, index) => {
            item.style.opacity = '0';
            item.style.transform = 'translateY(20px)';

            setTimeout(() => {
                item.style.transition = 'all 0.5s ease';
                item.style.opacity = '1';
                item.style.transform = 'translateY(0)';
            }, index * 150);
        });
    }

    async refreshStock() {
        try {
            await this.loadProducts();
            this.renderProducts();
        } catch (error) {
            console.error('Failed to refresh stock:', error);
        }
    }
}

function redirectToLicense(productId) {
    window.location.href = `license.html?product=${productId}`;
}

// Global instance for onclick handlers
let productManager;

document.addEventListener('DOMContentLoaded', () => {
    productManager = new ProductManager();
});
