class ProductManager {
    constructor() {
        this.products = [];
        this.user = null;
        if (window.__INITIAL_PRODUCTS__) {
            this._applyInitial(window.__INITIAL_PRODUCTS__);
        }
        this.init();
    }

    _applyInitial(data){
        try {
            if (!data) return;
            this.products = data.products || [];
            this.mainProducts = (data.mainProducts || []).map(mp => ({
                ...mp,
                variants: (mp.variantProducts || []).map(v => v.id)
            }));
        } catch(e) {
            console.warn('Failed applying initial products', e);
        }
    }

    async init() {
        await this.checkAuth();
        if (this.mainProducts && this.mainProducts.length) {
            this.renderProducts();
        }
        await this.loadProducts();
        this.renderProducts();
        this.renderAccountInfo();
        this.setupSearch();
        this.initStockStream();
    }

    async makeAuthenticatedRequest(url, options = {}) {
        const defaultOptions = {
            credentials: 'include',
            ...options
        };

        return fetch(url, defaultOptions);
    }

    async checkAuth() {

        try {
            const response = await this.makeAuthenticatedRequest('/me');

            if (response.ok) {
                const data = await response.json();
                if (data.authenticated) {
                    this.user = data.user;
                    this.renderAccountInfo();
                    return;
                }
            }

            console.log('Server authentication failed, clearing cached data');
            this.user = null;
            this.renderAccountInfo();

        } catch (error) {
            console.error('Auth check failed:', error);
            console.log('Network error during auth check, clearing cached data');
            this.user = null;
            this.renderAccountInfo();
        }
    }

    _renderSkeletons(count=3){
        const container = document.getElementById('products-container');
        if(!container) return;
        const skeleton = Array.from({length:count}).map(()=>`
            <div class="product-card skeleton-card">
                <div class="product-image-section skeleton skeleton-image"></div>
                <div class="skeleton skeleton-text" style="width:70%; margin:0.75rem auto 0.25rem;"></div>
                <div class="skeleton skeleton-text" style="width:40%; margin:0.25rem auto;"></div>
                <div class="skeleton skeleton-text" style="width:55%; margin:0.75rem auto;"></div>
                <div class="skeleton skeleton-text" style="width:90%; height:34px; border-radius:8px; margin-top:.75rem;"></div>
            </div>`).join('');
        container.innerHTML = skeleton;
    }

    showToast(message,type='error',timeout=5000){
        const c=document.getElementById('toast-container');
        if(!c) return;
        const el=document.createElement('div');
        el.className='toast '+(type==='error'?'toast-error':(type==='success'?'toast-success':''));
        el.innerHTML=`<span>${message}</span><button class="toast-close" aria-label="Close">×</button>`;
        c.appendChild(el);
        const remove=()=>{el.style.animation='toast-out .25s forwards';setTimeout(()=>el.remove(),230);};
        el.querySelector('.toast-close').onclick=remove;
        if(timeout>0) setTimeout(remove,timeout);
    }

    async loadProducts() {
        try {
            if(!this.mainProducts || !this.mainProducts.length){
                this._renderSkeletons(4);
            }
            let response;
            try {
                response = await fetch('/products', { cache: 'no-cache' });
            } catch (serverError) {
                this.showToast('Server unavailable, loading fallback','error');
                response = await fetch('config/products.json', { cache: 'no-cache' });
            }
            const data = await response.json();
            this.products = data.products || [];
            this.mainProducts = (data.mainProducts || []).map(mainProduct => {
                const variants = (mainProduct.variantProducts || []).length ? mainProduct.variantProducts : this.products.filter(p => p.parentProduct === mainProduct.id);
                const minPrice = variants.length > 0 ? Math.min(...variants.map(v => v.price || v.minPrice || 0)) : 0;
                const totalStock = variants.length > 0 ? variants.reduce((sum, v) => sum + (v.stock || v.totalStock || 0), 0) : 0;
                return { ...mainProduct, minPrice, totalStock, variants: variants.map(v => v.id) };
            });
        } catch (error) {
            this.showToast('Failed to load products','error');
            if (!this.products.length) {
                this.products = [];
                this.mainProducts = [];
            }
        }
    }

    setupSearch() {
        const searchInput = document.getElementById('product-search');
        if (!searchInput) return;

        let searchTimeout;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this.performSearch(e.target.value.trim());
            }, 300);
        });

        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.target.value = '';
                this.performSearch('');
            }
        });
    }

    performSearch(searchTerm) {
        const resultsInfo = document.getElementById('search-results-info');
        const container = document.getElementById('products-container');

        if (!searchTerm) {
            resultsInfo.style.display = 'none';
            this.renderRegularProducts();
            return;
        }

        const filteredProducts = this.mainProducts.filter(product => {
            const searchLower = searchTerm.toLowerCase();
            return (
                product.name.toLowerCase().includes(searchLower) ||
                (product.description && product.description.toLowerCase().includes(searchLower)) ||
                (product.tags && product.tags.some(tag => tag.toLowerCase().includes(searchLower)))
            );
        });

        resultsInfo.style.display = 'block';
        if (filteredProducts.length === 0) {
            resultsInfo.textContent = `No products found for "${searchTerm}"`;
        } else if (filteredProducts.length === 1) {
            resultsInfo.textContent = `Found 1 product for "${searchTerm}"`;
        } else {
            resultsInfo.textContent = `Found ${filteredProducts.length} products for "${searchTerm}"`;
        }

        this.renderFilteredProducts(filteredProducts, searchTerm);
    }

    renderFilteredProducts(products, searchTerm) {
        const container = document.getElementById('products-container');
        if (!container) return;

        if (products.length === 0) {
            container.innerHTML = `
                <div class="no-results">
                    <h3>No products found</h3>
                    <p>Try searching for "executor", "tool", or browse all products below.</p>
                    <button class="btn" onclick="productManager.clearSearch()" style="margin-top: 1rem; padding: 0.5rem 1rem; background: #6366f1; color: white; border: none; border-radius: 6px; cursor: pointer;">
                        Show All Products
                    </button>
                </div>
            `;
            return;
        }

        const productsHtml = products.map(product => {
            let stockText = product.totalStock > 0 ? `${product.totalStock} in Stock` : 'Out of Stock';
            let stockClass = product.totalStock > 0 ? 'in-stock' : 'out-of-stock';
            let isDisabled = product.totalStock === 0;

            const mainImageSrc = product.mainImage || (product.images && product.images[0]) || '';

            const highlightedName = this.highlightSearchTerm(product.name, searchTerm);

            return `
                <div class="product-card" data-product-id="${product.id}">
                    <div class="product-image-section">
                        <div class="image-carousel" data-images='${JSON.stringify(product.images)}'>
                            <img src="${mainImageSrc}" alt="${product.name}" class="carousel-image active" loading="lazy" width="324" height="172">
                        </div>
                    </div>
                    
                    <h3 class="product-title">${highlightedName}</h3>
                    
                    <div class="product-price-stock-row">
                        <div class="product-price">
                            <span class="price-label">Price:</span>
                            <span class="price-value">
                                <img src="icon/Robux.svg" alt="Robux" class="robux-icon" width="14" height="14" loading="lazy"> ${product.minPrice}
                            </span>
                        </div>
                        <div class="product-stock ${stockClass}">${stockText}</div>
                    </div>
                    
                    <button class="purchase-btn" onclick="redirectToProduct('${product.id}')" ${isDisabled ? 'disabled' : ''}>
                        ${isDisabled ? 'Out of Stock' : 'Purchase'}
                    </button>
                </div>
            `;
        }).join('');

        container.innerHTML = productsHtml;
    }

    highlightSearchTerm(text, searchTerm) {
        if (!searchTerm) return text;

        const regex = new RegExp(`(${searchTerm})`, 'gi');
        return text.replace(regex, '<mark style="background: rgba(99, 102, 241, 0.3); color: #ffffff; padding: 0 2px; border-radius: 2px;">$1</mark>');
    }

    clearSearch() {
        const searchInput = document.getElementById('product-search');
        const resultsInfo = document.getElementById('search-results-info');

        if (searchInput) searchInput.value = '';
        if (resultsInfo) resultsInfo.style.display = 'none';

        this.renderRegularProducts();
    }

    renderProducts() {
        this.renderFeaturedProducts();
        this.renderRegularProducts();
    }

    initStockStream() {
        try {
            if (!window.EventSource) {
                console.warn('EventSource not supported in this browser.');
                return;
            }
            this.stockSource = new EventSource('/stock-stream');
            this.stockSource.onmessage = (ev) => {
                try {
                    const data = JSON.parse(ev.data);
                    this.applyLiveStock(data);
                } catch (e) {
                    console.warn('Failed to parse stock event', e);
                }
            };
            this.stockSource.onerror = () => {
                if (this.stockSource.readyState === EventSource.CLOSED) {
                    setTimeout(() => this.initStockStream(), 4000);
                }
            };
        } catch (e) {
            console.warn('SSE init failed', e);
        }
    }

    applyLiveStock(snapshot) {
        if (!snapshot || !snapshot.products) return;
        let changed = false;
        for (const pid in snapshot.products) {
            const info = snapshot.products[pid];
            const existing = this.products.find(p => p.id === pid);
            if (existing && typeof info.stock === 'number' && existing.stock !== info.stock) {
                existing.stock = info.stock;
                changed = true;
            }
        }
        if (Array.isArray(snapshot.mainProducts)) {
            snapshot.mainProducts.forEach(mp => {
                const target = this.mainProducts.find(p => p.id === mp.id);
                if (target) {
                    if (typeof mp.totalStock === 'number' && target.totalStock !== mp.totalStock) {
                        target.totalStock = mp.totalStock;
                        changed = true;
                    }
                    if (typeof mp.minPrice === 'number') {
                        target.minPrice = mp.minPrice;
                    }
                }
            });
        } else {
            this.mainProducts.forEach(mp => {
                const variants = this.products.filter(p => p.parentProduct === mp.id);
                const total = variants.reduce((sum, v) => sum + (typeof v.stock === 'number' ? v.stock : 0), 0);
                if (total !== mp.totalStock) {
                    mp.totalStock = total;
                    changed = true;
                }
            });
        }
        if (changed) {
            this.renderRegularProducts();
        }
    }

    renderFeaturedProducts() {
        const featuredContainer = document.getElementById('featured-slides');
        const dotsContainer = document.getElementById('carousel-dots');
        if (!featuredContainer || !dotsContainer) return;

        const featuredProducts = this.mainProducts.slice(0, 3);

        if (featuredProducts.length === 0) return;

        const featuredHtml = featuredProducts.map((product) => {
            const mainImageSrc = product.mainImage || (product.images && product.images[0]) || '';

            return `
                <div class="featured-slide">
                    <div class="featured-card" onclick="redirectToProduct('${product.id}')">
                        <img src="${mainImageSrc}" alt="${product.name}" class="featured-image" loading="lazy" width="800" height="300">
                        <div class="featured-overlay"></div>
                        
                        <div class="featured-price-badge">
                            <div class="featured-price-label">Starting At</div>
                            <div class="featured-price-value">
                                <img src="icon/Robux.svg" alt="Robux" class="robux-icon" width="16" height="16" loading="lazy">
                                ${product.minPrice}
                            </div>
                        </div>
                        
                        <div class="featured-content">
                            <h3 class="featured-product-title">${product.name}</h3>
                            <p class="featured-description">${product.description || 'Premium Roblox tool with advanced features.'}</p>
                            <button class="featured-purchase-btn">Purchase</button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        const dotsHtml = featuredProducts.map((_, index) =>
            `<div class="carousel-dot ${index === 0 ? 'active' : ''}" onclick="goToSlide(${index})"></div>`
        ).join('');

        featuredContainer.innerHTML = featuredHtml;
        dotsContainer.innerHTML = dotsHtml;

        this.startCarousel(featuredProducts.length);
    }

    renderRegularProducts() {
        const container = document.getElementById('products-container');
        if (!container) return;

        if (!this.mainProducts || this.mainProducts.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 3rem; color: #a1a1aa;">
                    <h3 style="color: #ffffff; margin-bottom: 0.5rem;">No products available</h3>
                    <p>Products will appear here when available.</p>
                </div>
            `;
            return;
        }

        const productsHtml = this.mainProducts.map(product => {
            let stockText = product.totalStock > 0 ? `${product.totalStock} in Stock` : 'Out of Stock';
            let stockClass = product.totalStock > 0 ? 'in-stock' : 'out-of-stock';
            let isDisabled = product.totalStock === 0;

            const mainImageSrc = product.mainImage || (product.images && product.images[0]) || '';
            const imagesHtml = `<img src="${mainImageSrc}" alt="${product.name}" class="carousel-image active" loading="lazy" width="324" height="172">`;

            return `
                <div class="product-card" data-product-id="${product.id}">
                    <div class="product-image-section">
                        <div class="image-carousel" data-images='${JSON.stringify(product.images)}'>
                            ${imagesHtml}
                        </div>
                    </div>
                    
                    <h3 class="product-title">${product.name}</h3>
                    
                    <div class="product-price-stock-row">
                        <div class="product-price">
                            <span class="price-label">Price:</span>
                            <span class="price-value">
                                <img src="icon/Robux.svg" alt="Robux" class="robux-icon" width="14" height="14" loading="lazy"> ${product.minPrice}
                            </span>
                        </div>
                        <div class="product-stock ${stockClass}">${stockText}</div>
                    </div>
                    
                    <button class="purchase-btn" onclick="redirectToProduct('${product.id}')" ${isDisabled ? 'disabled' : ''}>
                        ${isDisabled ? 'Out of Stock' : 'Purchase'}
                    </button>
                </div>
            `;
        }).join('');

        container.innerHTML = productsHtml;
        this.addProductAnimations();
    }

    startCarousel(totalSlides) {
        if (totalSlides <= 1) return;

        let currentSlide = 0;

        this.carouselInterval = setInterval(() => {
            currentSlide = (currentSlide + 1) % totalSlides;
            this.goToSlide(currentSlide);
        }, 4000);
    }

    goToSlide(slideIndex) {
        const slidesContainer = document.getElementById('featured-slides');
        const dots = document.querySelectorAll('.carousel-dot');

        if (slidesContainer) {
            slidesContainer.style.transform = `translateX(-${slideIndex * 100}%)`;
        }

        dots.forEach((dot, index) => {
            dot.classList.toggle('active', index === slideIndex);
        });
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
            this._renderSkeletons(2);
            await this.loadProducts();
            this.renderProducts();
        } catch (error) {
            this.showToast('Stock refresh failed','error');
        }
    }

    renderAccountInfo() {
        const userInfo = document.getElementById('user-info');
        const authSection = document.getElementById('auth-section');
        const usernameDisplay = document.getElementById('username-display');
        const logoutBtn = document.getElementById('logout-btn');
        const loginBtn = document.getElementById('login-btn');

        if (this.user && userInfo && authSection && usernameDisplay) {
            usernameDisplay.textContent = this.user.username;
            userInfo.style.display = 'flex';
            authSection.style.display = 'none';

            if (logoutBtn) {
                logoutBtn.onclick = logout;
            }
        } else if (userInfo && authSection) {
            userInfo.style.display = 'none';
            authSection.style.display = 'block';

            if (loginBtn) {
                const returnUrl = encodeURIComponent(window.location.href);
                loginBtn.href = `auth.html?return=${returnUrl}`;
            }
        }
    }
}

function redirectToProduct(productId) {
    window.location.href = `product.html?id=${productId}`;
}

function redirectToLicense(productId) {
    window.location.href = `license.html?product=${productId}`;
}

function nextImage(button) {
    const carousel = button.closest('.image-carousel');
    const images = carousel.querySelectorAll('.carousel-image');
    const activeImage = carousel.querySelector('.carousel-image.active');
    const currentIndex = Array.from(images).indexOf(activeImage);
    const nextIndex = (currentIndex + 1) % images.length;

    activeImage.classList.remove('active');
    images[nextIndex].classList.add('active');
}

function previousImage(button) {
    const carousel = button.closest('.image-carousel');
    const images = carousel.querySelectorAll('.carousel-image');
    const activeImage = carousel.querySelector('.carousel-image.active');
    const currentIndex = Array.from(images).indexOf(activeImage);
    const prevIndex = currentIndex === 0 ? images.length - 1 : currentIndex - 1;

    activeImage.classList.remove('active');
    images[prevIndex].classList.add('active');
}

async function logout() {
    try {
    await productManager.makeAuthenticatedRequest('/logout', {
            method: 'POST'
        });
        window.location.reload();
    } catch (error) {
        console.error('Logout failed:', error);
        window.location.reload();
    }
}

function goToSlide(slideIndex) {
    if (productManager) {
        productManager.goToSlide(slideIndex);
    }
}

function clearSearch() {
    if (productManager) {
        productManager.clearSearch();
    }
}

let productManager;

document.addEventListener('DOMContentLoaded', () => {
    productManager = new ProductManager();

    document.addEventListener('keydown', (e) => {
        if (e.key.toLowerCase() === 's' && !e.target.matches('input, textarea')) {
            e.preventDefault();
            const searchInput = document.getElementById('product-search');
            if (searchInput) {
                searchInput.focus();
            }
        }

        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            if (productManager) {
                productManager.clearSearch();
                const searchInput = document.getElementById('product-search');
                if (searchInput) {
                    searchInput.focus();
                }
            }
        }
    });
});
